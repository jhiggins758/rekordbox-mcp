"""Batch drop proposals for uncued primary-genre tracks, sorted into confidence tiers.

Read-only: analyzes audio and prints a report. Nothing is written to rekordbox —
applying cues and creating the C-inbox playlist are separate, approval-gated
steps driven by the /cue-tracks skill.

    uv run --with librosa --with soundfile --with scikit-learn --with lightgbm --with numpy \
        python cue_batch.py [N]           # analyze up to N uncued tracks (default 40)

Output: table per tier + cue_batch_results.json (resumable across runs).
"""

import os
import sys
import json
import pickle
import asyncio
import warnings

warnings.filterwarnings("ignore")
import numpy as np

from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from djtk_config import load_config, open_db, workspace, genre_match
from cue_model import build_file_index, resolve, beat_times_ms, ladder_from_anchor
import cue_extract
import cue_train

from pyrekordbox.db6 import tables

CFG = load_config()
OUT = str(workspace(CFG, "cue_batch_results.json"))
RANKER = pickle.load(open(workspace(CFG, "cue_ranker.pkl"), "rb"))
CONF = json.load(open(workspace(CFG, "cue_confidence.json")))


def tier_of(margin):
    hi, mid = CONF["tercile_edges"]
    if margin >= hi:
        return "high"
    if margin >= mid:
        return "medium"
    return "low"


def tier_rate(tier):
    for t in CONF["tiers"]:
        if t["tier"] == tier:
            return t["exact_rate"]
    return None


async def main():
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 40

    d = await open_db(CFG)
    print("indexing audio files...", flush=True)
    fidx = build_file_index()

    cued = {
        str(c.ContentID)
        for c in d.db.query(tables.DjmdCue).all()
        if not (c.rb_local_deleted or 0)
    }

    prev = {}
    if os.path.exists(OUT):
        prev = {r["track_id"]: r for r in json.load(open(OUT, encoding="utf-8"))}

    targets = []
    for c in d.db.get_content():
        if (c.rb_local_deleted or 0) or str(c.ID) in cued:
            continue
        genre = (getattr(getattr(c, "Genre", None), "Name", "") or "")
        if not genre_match(CFG, "primary", genre, (c.BPM or 0) / 100.0):
            continue
        targets.append(c)
    print(f"uncued primary-family tracks: {len(targets)} | already analyzed: {len(prev)}", flush=True)

    results = list(prev.values())
    fresh = 0
    for c in targets:
        tid = str(c.ID)
        if tid in prev:
            continue
        if fresh >= limit:
            break
        times = beat_times_ms(d.db, c)
        path = resolve(c, fidx)
        if times is None or len(times) < 128 or not path or not os.path.exists(path):
            continue
        try:
            cols = cue_extract.per_beat_features(path, times)
        except Exception:
            continue
        if cols is None:
            continue
        rec = {"arrs": cols, "n_beats": len(times), "bpm": (c.BPM or 0) / 100.0}
        artist = getattr(getattr(c, "Artist", None), "Name", "") or ""
        ap = RANKER["artist_prior"].get(artist, RANKER["global_prior"])
        tc = cue_train.track_candidates(rec, ap)
        if tc is None:
            continue
        beats, feats = tc
        scores = cue_train.model_scores(RANKER["model"], feats)
        order = np.argsort(-scores)
        drop = cue_train.refine(rec, beats[order[0]])
        margin = float(scores[order[0]] - scores[order[1]]) if len(order) > 1 else 0.0
        tier = tier_of(margin)
        results.append(
            {
                "track_id": tid,
                "title": c.Title or "",
                "artist": artist,
                "bpm": rec["bpm"],
                "tier": tier,
                "margin": round(margin, 3),
                "drop_beat": int(drop),
                "drop_ms": int(round(times[drop])),
                "alternates_ms": [int(round(times[beats[o]])) for o in order[1:3]],
                "cues": ladder_from_anchor(c, times, int(drop), set())[1],
            }
        )
        fresh += 1
        if fresh % 10 == 0:
            print(f"  {fresh} analyzed...", flush=True)

    json.dump(results, open(OUT, "w", encoding="utf-8"), indent=1)

    def fmt_ms(ms):
        return f"{ms//60000}:{(ms % 60000)//1000:02d}.{ms % 1000:03d}"

    print(f"\n{'='*72}")
    for tier in ("high", "medium", "low"):
        rows = [r for r in results if r["tier"] == tier]
        rate = tier_rate(tier)
        print(f"\n{tier.upper()} confidence — est. {100*rate:.0f}% beat-perfect ({len(rows)} tracks)")
        for r in sorted(rows, key=lambda x: -x["margin"])[:25]:
            print(f"  {r['track_id']:>12}  drop {fmt_ms(r['drop_ms'])}  {r['artist'][:20]:20s} {r['title'][:38]}")
        if len(rows) > 25:
            print(f"  ... and {len(rows)-25} more")
    print(f"\nwrote {OUT} ({len(results)} tracks total)")
    await d.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
