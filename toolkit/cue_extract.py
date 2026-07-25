"""Per-beat feature extraction for the DnB auto-cue ranker (resumable JSONL).

For every DnB track (160-180 BPM) with a hand-placed C cue, a beat grid and a
resolvable audio file: decode the first ~65% of the track and store per-beat
arrays of the signals a drop is made of —

    bb   broadband energy (dB)
    sb   sub-bass 20-120 Hz (dB)          the impact
    hi   4-11 kHz (dB)                    risers / builds live up here
    cen  spectral centroid (kHz)          rises into a drop
    on   onset strength                   drum fills / density

plus the ground truth (the beat index of the C cue). The heavy audio decode
happens once, here; cue_train.py then engineers candidate features and fits
models from these arrays in seconds.

    uv run --with librosa --with soundfile --with numpy python cue_extract.py
"""

import os
import sys
import json
import asyncio
import warnings

warnings.filterwarnings("ignore")
import numpy as np
import librosa

from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from djtk_config import load_config, open_db, workspace, genre_match
from cue_model import build_file_index, resolve, beat_times_ms, cue_system, SLOT_TO_KIND

from pyrekordbox.db6 import tables

CFG = load_config()
OUT = str(workspace(CFG, "cue_beat_features.jsonl"))
ANCHOR_KIND = SLOT_TO_KIND[cue_system()["anchor_slot"]]
LOAD_FRACTION = 0.65  # drops live 8-50% in; 65% leaves margin without full decode


def per_beat_features(path, times):
    duration = float(times[-1]) / 1000.0 * LOAD_FRACTION + 10.0
    y, sr = librosa.load(path, sr=22050, mono=True, duration=duration)
    if y.size < sr * 30:
        return None

    hop = 512
    S = np.abs(librosa.stft(y, n_fft=2048, hop_length=hop)) + 1e-9
    freqs = librosa.fft_frequencies(sr=sr, n_fft=2048)
    frame_t = librosa.frames_to_time(np.arange(S.shape[1]), sr=sr, hop_length=hop) * 1000.0

    bb = librosa.amplitude_to_db(S.sum(axis=0))
    sb = librosa.amplitude_to_db(S[(freqs >= 20) & (freqs < 120)].sum(axis=0))
    hi = librosa.amplitude_to_db(S[(freqs >= 4000)].sum(axis=0))
    cen = librosa.feature.spectral_centroid(S=S, sr=sr)[0] / 1000.0
    on = librosa.onset.onset_strength(S=librosa.power_to_db(S**2), sr=sr)
    # onset envelope can be one frame shorter than the STFT
    if on.shape[0] < S.shape[1]:
        on = np.pad(on, (0, S.shape[1] - on.shape[0]))

    n = len(times)
    cols = {k: np.full(n, np.nan) for k in ("bb", "sb", "hi", "cen", "on")}
    src = {"bb": bb, "sb": sb, "hi": hi, "cen": cen, "on": on}
    for i in range(n - 1):
        lo, hi_t = times[i], times[i + 1]
        if lo > frame_t[-1]:
            break
        m = (frame_t >= lo) & (frame_t < hi_t)
        if m.any():
            for k in cols:
                cols[k][i] = src[k][m].mean()
    return cols


async def main():
    d = await open_db(CFG)
    print("indexing audio files...", flush=True)
    fidx = build_file_index()
    print(f"file index: {len(fidx)}", flush=True)

    cues_by_track = {}
    for c in d.db.query(tables.DjmdCue).all():
        if not (c.rb_local_deleted or 0):
            cues_by_track.setdefault(str(c.ContentID), []).append(c)

    done = set()
    if os.path.exists(OUT):
        for line in open(OUT, encoding="utf-8"):
            try:
                done.add(json.loads(line)["id"])
            except Exception:
                pass
    print(f"already extracted: {len(done)}", flush=True)

    targets = []
    for tid, cl in cues_by_track.items():
        a_cue = [c for c in cl if int(c.Kind or 0) == ANCHOR_KIND]
        if not a_cue:
            continue
        content = d.db.get_content(ID=int(tid))
        if content is None or (content.rb_local_deleted or 0):
            continue
        genre = (getattr(getattr(content, "Genre", None), "Name", "") or "")
        if not genre_match(CFG, "primary", genre, (content.BPM or 0) / 100.0):
            continue
        targets.append((content, int(a_cue[0].InMsec or 0)))
    print(f"primary-family tracks with an anchor cue: {len(targets)}", flush=True)

    ok = skip = fail = 0
    fh = open(OUT, "a", encoding="utf-8")
    for content, c_ms in targets:
        tid = str(content.ID)
        if tid in done:
            continue
        times = beat_times_ms(d.db, content)
        path = resolve(content, fidx)
        if times is None or len(times) < 128 or not path or not os.path.exists(path):
            skip += 1
            continue
        try:
            cols = per_beat_features(path, times)
        except Exception:
            fail += 1
            continue
        if cols is None:
            skip += 1
            continue

        c_beat = int(np.argmin(np.abs(times - c_ms)))
        rec = {
            "id": tid,
            "title": content.Title or "",
            "artist": getattr(getattr(content, "Artist", None), "Name", "") or "",
            "bpm": round((content.BPM or 0) / 100.0, 1),
            "n_beats": len(times),
            "c_beat": c_beat,
            "c_offgrid": int(abs(times[c_beat] - c_ms)),  # ms between cue and its beat
        }
        for k, v in cols.items():
            rec[k] = [None if np.isnan(x) else round(float(x), 2) for x in v]
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        fh.flush()
        ok += 1
        if ok % 25 == 0:
            print(f"  extracted {ok} (skip {skip}, fail {fail})", flush=True)
    fh.close()
    print(f"\nDONE: extracted {ok}, skipped {skip}, failed {fail}", flush=True)
    await d.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
