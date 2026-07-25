"""Batch-extract audio features for the library (resumable JSONL). Primary genre first.

Config: music_roots (file resolution), character_tags (melodic/heavy label tags),
genres (processing order). Output: workspace/audio_features.jsonl.

    uv run --with librosa --with soundfile --with numpy python toolkit/extract_features.py
"""
import os, sys, json, asyncio, warnings
from pathlib import Path
warnings.filterwarnings("ignore")
import numpy as np, librosa
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).parent))
from djtk_config import load_config, open_db, workspace, genre_match
from pyrekordbox.db6 import tables

CFG = load_config()
OUT = str(workspace(CFG, "audio_features.jsonl"))
ROOTS = [str(Path(r).expanduser()) for r in (CFG.get("music_roots") or [])]
EXTS = (".mp3", ".wav", ".flac", ".m4a", ".aif", ".aiff")
MELODIC = set((CFG.get("character_tags") or {}).get("melodic") or [])
HEAVY = set((CFG.get("character_tags") or {}).get("heavy") or [])

def feats(path, length):
    off = max(0, min((length or 200) * 0.35, (length or 200) - 26))
    y, sr = librosa.load(path, sr=22050, offset=off, duration=25.0, mono=True)
    if y.size < sr: return None
    S = np.abs(librosa.stft(y, n_fft=2048, hop_length=1024)) + 1e-9
    fr = librosa.fft_frequencies(sr=sr, n_fft=2048)
    tot = S.sum()
    band = lambda lo, hi: float(S[(fr >= lo) & (fr < hi)].sum() / tot)
    rms = librosa.feature.rms(S=S)[0]
    return {
        "sub": band(20, 120), "lowmid": band(120, 500), "mid": band(500, 2000),
        "hi": band(4000, 11025),
        "centroid": float(librosa.feature.spectral_centroid(S=S, sr=sr).mean()),
        "rolloff": float(librosa.feature.spectral_rolloff(S=S, sr=sr, roll_percent=0.85).mean()),
        "bandwidth": float(librosa.feature.spectral_bandwidth(S=S, sr=sr).mean()),
        "flatness": float(librosa.feature.spectral_flatness(S=S).mean()),
        "zcr": float(librosa.feature.zero_crossing_rate(y, hop_length=1024).mean()),
        "rms": float(rms.mean()), "crest": float(rms.max() / (rms.mean() + 1e-9)),
    }

async def main():
    d = await open_db(CFG)
    active = [c for c in d.db.get_content() if getattr(c, "rb_local_deleted", 0) == 0]
    tag_name = {str(t.ID): t.Name for t in d.db.get_my_tag() if getattr(t, "rb_local_deleted", 0) == 0}
    tt = defaultdict(list)
    for s in d.db.query(tables.DjmdSongMyTag):
        if getattr(s, "rb_local_deleted", 0) == 0 and str(s.MyTagID) in tag_name:
            tt[str(s.ContentID)].append(tag_name[str(s.MyTagID)])

    fidx = {}
    for root in ROOTS:
        if not os.path.exists(root): continue
        for dp, _, files in os.walk(root):
            for f in files:
                if f.lower().endswith(EXTS): fidx.setdefault(f.lower(), os.path.join(dp, f))
    print(f"file index: {len(fidx)}", flush=True)

    done = set()
    if os.path.exists(OUT):
        for line in open(OUT, encoding="utf-8"):
            try: done.add(json.loads(line)["id"])
            except Exception: pass
    print(f"already done: {len(done)}", flush=True)

    def resolve(c):
        fp = c.FolderPath or ""
        if os.path.exists(fp): return fp
        return fidx.get(os.path.basename(fp.replace("\\", "/")).lower())

    families = list((CFG.get("genres") or {}).keys())
    def genre_rank(c):
        g = getattr(getattr(c, "Genre", None), "Name", "") or ""
        bpm = (c.BPM or 0) / 100.0
        for i, fam in enumerate(families):
            if genre_match(CFG, fam, g, bpm):
                return i
        return len(families)
    active.sort(key=genre_rank)

    n = ok = fail = skip = 0
    fh = open(OUT, "a", encoding="utf-8")
    for c in active:
        if str(c.ID) in done: continue
        n += 1
        path = resolve(c)
        if not path or not os.path.exists(path): skip += 1; continue
        try:
            f = feats(path, c.Length)
            if not f: skip += 1; continue
            tags = tt.get(str(c.ID), [])
            rec = {"id": str(c.ID), "title": c.Title or "",
                   "artist": getattr(getattr(c, "Artist", None), "Name", "") or "",
                   "genre": getattr(getattr(c, "Genre", None), "Name", "") or "",
                   "bpm": round((c.BPM or 0)/100, 1), "key": getattr(getattr(c, "Key", None), "ScaleName", None),
                   "rating": c.Rating or 0,
                   "mel": any(t in MELODIC for t in tags), "hvy": any(t in HEAVY for t in tags),
                   "chartags": [t for t in tags if t in MELODIC or t in HEAVY], "f": f}
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n"); fh.flush(); ok += 1
        except Exception:
            fail += 1
        if ok % 50 == 0 and ok: print(f"  extracted {ok} (skip {skip}, fail {fail})", flush=True)
    fh.close()
    print(f"\nDONE: extracted {ok}, skipped {skip} (no file), failed {fail}, total considered {n}", flush=True)
    await d.disconnect()

asyncio.run(main())
