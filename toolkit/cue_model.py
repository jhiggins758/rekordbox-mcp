"""Cue tools built on YOUR mined cue system (see mine_cue_system.py).

The reliable workflow: you set only the ANCHOR cue in rekordbox (you're listening
to the track anyway and you're never wrong about where it goes), and the toolkit
derives the rest of your ladder — pure beat-grid arithmetic, no audio guessing.
Measured ~99% faithful on the library this method was developed against.

    uv run --with numpy python toolkit/cue_model.py --scan-from-anchor
        list tracks that have the anchor cue but are missing ladder slots

    uv run --with numpy python toolkit/cue_model.py --from-anchor <track_id>
        print the derived ladder for one track (slot -> position ms)

    uv run --with librosa --with soundfile --with scikit-learn --with numpy \\
        python toolkit/cue_model.py --propose <track_id>
        audio drop-detection fallback for tracks with NO anchor yet. Uses the
        trained ranker (cue_train.py) when workspace/cue_ranker.pkl exists,
        otherwise a spectral heuristic. Expect ~55-65% beat-perfect at best —
        ALWAYS present for approval; never bulk-apply.

Read-only. Applying cues goes through the MCP's add_track_cue (rekordbox CLOSED).
"""

import os
import re
import sys
import json
import asyncio
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from djtk_config import load_config, open_db, workspace, genre_match

# librosa only needed for --propose; imported lazily so anchor modes run without it
librosa = None


def _need_librosa():
    global librosa
    if librosa is None:
        import librosa as _l
        librosa = _l
    return librosa


CFG = load_config()

KIND_TO_SLOT = {1: "A", 2: "B", 3: "C", 5: "D", 6: "E", 7: "F", 8: "G", 9: "H"}
SLOT_TO_KIND = {v: k for k, v in KIND_TO_SLOT.items()}


def cue_system():
    cs = CFG.get("cue_system")
    if not cs or not cs.get("anchor_slot"):
        raise SystemExit(
            "No cue_system in config. Run mine_cue_system.py --write first "
            "(needs ~50+ cued tracks), or add one by hand — see config.example.json."
        )
    return cs


def family_of(content):
    """Which configured genre family a track belongs to (None if neither)."""
    genre = (getattr(getattr(content, "Genre", None), "Name", "") or "")
    bpm = (content.BPM or 0) / 100.0
    for fam in (CFG.get("genres") or {}):
        if genre_match(CFG, fam, genre, bpm):
            return fam
    return None


def build_file_index():
    idx = {}
    exts = (".mp3", ".wav", ".flac", ".m4a", ".aif", ".aiff")
    for root in CFG.get("music_roots") or []:
        root = str(Path(root).expanduser())
        if not os.path.exists(root):
            continue
        for dp, _, files in os.walk(root):
            for f in files:
                if f.lower().endswith(exts):
                    idx.setdefault(f.lower(), os.path.join(dp, f))
    return idx


def resolve(content, fidx):
    fp = content.FolderPath or ""
    if os.path.exists(fp):
        return fp
    return fidx.get(os.path.basename(fp.replace("\\", "/")).lower())


def beat_times_ms(db, content):
    """Beat grid (ms) from ANLZ .DAT. NB: never use `in file`/`len(file)` on an
    AnlzFile — pyrekordbox 0.4.3's __len__ recurses; use tag_types / is None."""
    try:
        anlz = db.read_anlz_file(content, "DAT")
    except Exception:
        return None
    if anlz is None or "PQTZ" not in anlz.tag_types:
        return None
    try:
        return np.array(anlz.get_tag("PQTZ").get_times()) * 1000.0
    except Exception:
        return None


def ladder_from_anchor(content, times, anchor_beat, existing_kinds):
    """Derive every ladder slot from the user's anchor cue. Pure arithmetic."""
    cs = cue_system()
    fam = family_of(content) or next(iter(cs["ladders"]), None)
    ladder = (cs["ladders"] or {}).get(fam) or {}
    out = []
    for slot, offset in sorted(ladder.items(), key=lambda kv: kv[1]):
        beat = anchor_beat + int(offset)
        status = None
        if SLOT_TO_KIND.get(slot) in existing_kinds:
            status = "already set"
        elif beat < 0 or beat >= len(times):
            status = "no room"
        out.append({"slot": slot, "offset_beats": int(offset),
                    "beat": int(beat),
                    "position_ms": int(round(times[beat])) if 0 <= beat < len(times) else None,
                    "skip": status})
    return fam, out


# ---------------- audio drop detection (--propose fallback) ----------------

PHRASE = 32
SEARCH_LO, SEARCH_HI = 0.06, 0.52


def per_beat_features(path, times, load_fraction=0.65):
    """Per-beat broadband/sub-bass/high/centroid/onset arrays for the ranker."""
    lb = _need_librosa()
    duration = float(times[-1]) / 1000.0 * load_fraction + 10.0
    y, sr = lb.load(path, sr=22050, mono=True, duration=duration)
    if y.size < sr * 30:
        return None
    hop = 512
    S = np.abs(lb.stft(y, n_fft=2048, hop_length=hop)) + 1e-9
    freqs = lb.fft_frequencies(sr=sr, n_fft=2048)
    frame_t = lb.frames_to_time(np.arange(S.shape[1]), sr=sr, hop_length=hop) * 1000.0
    src = {
        "bb": lb.amplitude_to_db(S.sum(axis=0)),
        "sb": lb.amplitude_to_db(S[(freqs >= 20) & (freqs < 120)].sum(axis=0)),
        "hi": lb.amplitude_to_db(S[(freqs >= 4000)].sum(axis=0)),
        "cen": lb.feature.spectral_centroid(S=S, sr=sr)[0] / 1000.0,
        "on": None,
    }
    on = lb.onset.onset_strength(S=lb.power_to_db(S ** 2), sr=sr)
    if on.shape[0] < S.shape[1]:
        on = np.pad(on, (0, S.shape[1] - on.shape[0]))
    src["on"] = on
    n = len(times)
    cols = {k: np.full(n, np.nan) for k in src}
    for i in range(n - 1):
        lo, hi_t = times[i], times[i + 1]
        if lo > frame_t[-1]:
            break
        m = (frame_t >= lo) & (frame_t < hi_t)
        if m.any():
            for k in cols:
                cols[k][i] = src[k][m].mean()
    return cols


def heuristic_drop(cols, n_beats):
    """Spectral fallback: biggest sub-bass arrival at a phrase boundary, with a
    position prior. Rough (~35-60% exact depending on genre) — approval required."""
    bb, sb = cols["bb"], cols["sb"]
    valid = ~np.isnan(bb)
    if valid.sum() < 96:
        return None, []
    zb = (bb - np.nanmean(bb)) / (np.nanstd(bb) + 1e-9)
    zs = (sb - np.nanmean(sb)) / (np.nanstd(sb) + 1e-9)
    last = int(np.max(np.where(valid)[0]))
    lo = max(PHRASE, int(n_beats * SEARCH_LO))
    hi = min(last - PHRASE, int(n_beats * SEARCH_HI))
    cands = []
    for b in range(lo, hi + 1):
        if b % PHRASE:
            continue
        seg = lambda a, x, y: float(np.nanmean(a[max(0, x):max(0, y)])) if y > x else 0.0
        lift = (seg(zb, b, b + PHRASE) - seg(zb, b - PHRASE, b)) \
             + 1.5 * (seg(zs, b, b + PHRASE) - seg(zs, b - PHRASE, b))
        sub_level = seg(zs, b, b + PHRASE)
        prior = -0.5 * ((b / n_beats - 0.22) / 0.07) ** 2
        cands.append((0.5 * lift + 2.0 * sub_level + 8.0 * prior, b))
    cands.sort(key=lambda x: -x[0])
    return (cands[0][1] if cands else None), [b for _, b in cands[:3]]


async def main():
    args = sys.argv[1:]
    mode = args[0] if args else "--scan-from-anchor"
    cs = cue_system()
    anchor_kind = SLOT_TO_KIND[cs["anchor_slot"]]

    d = await open_db(CFG)
    db = d.db
    from pyrekordbox.db6 import tables

    cues_by_track = {}
    for c in db.query(tables.DjmdCue).all():
        if not (c.rb_local_deleted or 0):
            cues_by_track.setdefault(str(c.ContentID), []).append(c)

    if mode == "--scan-from-anchor":
        core_by_fam = cs.get("core_slots") or {f: list(l) for f, l in (cs.get("ladders") or {}).items()}
        rows = []
        for tid, cl in cues_by_track.items():
            kinds = {int(c.Kind or 0) for c in cl}
            if anchor_kind not in kinds:
                continue
            content = db.get_content(ID=int(tid))
            if content is None or (content.rb_local_deleted or 0):
                continue
            fam = family_of(content)
            core = core_by_fam.get(fam) if fam else None
            if not core:
                continue
            missing = [s for s in core if SLOT_TO_KIND.get(s) not in kinds]
            if missing:
                rows.append((tid, content.Title or "", missing))
        print(f"tracks with the {cs['anchor_slot']} anchor but missing CORE ladder slots: {len(rows)}\n")
        for tid, title, missing in rows[:40]:
            print(f"  {tid:>12}  missing {','.join(sorted(missing)):12s}  {title[:52]}")
        if len(rows) > 40:
            print(f"  ... and {len(rows) - 40} more")
        await d.disconnect()
        return

    if mode == "--from-anchor":
        tid = args[1]
        content = db.get_content(ID=int(tid))
        times = beat_times_ms(db, content)
        if times is None:
            print(json.dumps({"error": "no beat grid — analyze the track in rekordbox first"}))
            await d.disconnect()
            return
        cl = cues_by_track.get(tid, [])
        existing = {int(c.Kind or 0) for c in cl}
        anchor = [c for c in cl if int(c.Kind or 0) == anchor_kind]
        if not anchor:
            print(json.dumps({"error": f"no {cs['anchor_slot']} cue on this track — set the anchor in rekordbox first"}))
            await d.disconnect()
            return
        a_ms = int(anchor[0].InMsec or 0)
        a_beat = int(np.argmin(np.abs(times - a_ms)))
        fam, ladder = ladder_from_anchor(content, times, a_beat, existing)
        print(json.dumps({"track_id": tid, "title": content.Title or "",
                          "family": fam, "anchor_ms": a_ms, "anchor_beat": a_beat,
                          "cues": ladder}, indent=1))
        await d.disconnect()
        return

    if mode == "--propose":
        tid = args[1]
        content = db.get_content(ID=int(tid))
        times = beat_times_ms(db, content)
        fidx = build_file_index()
        path = resolve(content, fidx)
        if times is None or not path:
            print(json.dumps({"error": "no beat grid or audio file"}))
            await d.disconnect()
            return
        cols = per_beat_features(path, times)
        if cols is None:
            print(json.dumps({"error": "could not decode audio"}))
            await d.disconnect()
            return
        ranker = workspace(CFG, "cue_ranker.pkl")
        drop, alts, engine = None, [], "heuristic"
        if ranker.exists():
            import pickle
            import cue_train
            bundle = pickle.load(open(ranker, "rb"))
            rec = {"arrs": cols, "n_beats": len(times), "bpm": (content.BPM or 0) / 100.0}
            artist = (getattr(getattr(content, "Artist", None), "Name", "") or "")
            ap = bundle["artist_prior"].get(artist, bundle["global_prior"])
            tc = cue_train.track_candidates(rec, ap)
            if tc is not None:
                beats, feats = tc
                scores = cue_train.model_scores(bundle["model"], feats)
                order = np.argsort(-scores)
                drop = cue_train.refine(rec, beats[order[0]])
                alts = [int(beats[o]) for o in order[1:3]]
                engine = "learned-ranker"
        if drop is None:
            drop, top3 = heuristic_drop(cols, len(times))
            alts = top3[1:3]
        if drop is None:
            print(json.dumps({"error": "no drop candidate found"}))
            await d.disconnect()
            return
        fam, ladder = ladder_from_anchor(content, times, int(drop), set())
        print(json.dumps({"track_id": tid, "title": content.Title or "",
                          "engine": engine, "family": fam,
                          "drop_beat": int(drop), "drop_ms": int(round(times[int(drop)])),
                          "alternate_drops_ms": [int(round(times[b])) for b in alts if 0 <= b < len(times)],
                          "cues": ladder}, indent=1))
        await d.disconnect()
        return

    print(__doc__)
    await d.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
