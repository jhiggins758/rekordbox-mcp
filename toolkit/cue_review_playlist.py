"""Create a rekordbox playlist of a cue batch, ordered high -> low confidence.

Reads cue_batch_results.json and builds one playlist inside the "Cue
Review" folder, sorted by confidence tier then score margin, so the tracks the
model is surest about sit at the top and the ones needing a hand-placed C sit at
the bottom. Prints the tier boundaries (which playlist positions are which tier)
since rekordbox itself shows only the order.

Requires rekordbox CLOSED (it writes to the database; a backup is taken first).

    uv run --with numpy python cue_review_playlist.py            # dry run: show the order
    uv run --with numpy python cue_review_playlist.py --apply    # create the playlist
"""

import os
import sys
import json
import asyncio
from datetime import date

from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from djtk_config import load_config, open_db, workspace

CFG = load_config()
RESULTS = str(workspace(CFG, "cue_batch_results.json"))
FOLDER = "Cue Review"
TIER_ORDER = {"high": 0, "medium": 1, "low": 2}
APPLY = "--apply" in sys.argv


def fmt_ms(ms):
    return f"{ms//60000}:{(ms % 60000)//1000:02d}"


def pid_of(res):
    """create_playlist returns either an id string or a dict."""
    if isinstance(res, str):
        return res
    return str(res.get("id") or res.get("playlist_id"))


async def main():
    if not os.path.exists(RESULTS):
        print(f"no batch results at {RESULTS} — run cue_batch.py first")
        return
    rows = json.load(open(RESULTS, encoding="utf-8"))
    rows.sort(key=lambda r: (TIER_ORDER.get(r["tier"], 9), -r["margin"]))
    name = f"Cue Review ({date.today().isoformat()})"

    print(f"{len(rows)} tracks, ordered high -> low confidence\n")
    bounds = {}
    for i, r in enumerate(rows, 1):
        bounds.setdefault(r["tier"], [i, i])[1] = i
        if i <= 12 or i > len(rows) - 5:
            print(f"  {i:3d}. [{r['tier']:6s}] drop {fmt_ms(r['drop_ms']):>6}  "
                  f"{r['artist'][:22]:22s} {r['title'][:40]}")
        elif i == 13:
            print(f"       ... {len(rows)-17} more ...")

    print("\nplaylist positions by tier:")
    for tier in ("high", "medium", "low"):
        if tier in bounds:
            lo, hi = bounds[tier]
            print(f"  {tier:6s}: tracks {lo}-{hi}")

    if not APPLY:
        print(f"\nDry run — nothing written. Re-run with --apply to create '{name}'.")
        return

    d = await open_db(CFG)

    folder_id = None
    for p in d.db.get_playlist():
        if (
            getattr(p, "rb_local_deleted", 0) == 0
            and p.Name == FOLDER
            and getattr(p, "Attribute", 0) == 1
        ):
            folder_id = str(p.ID)
            break
    if folder_id is None:
        folder_id = pid_of(await d.create_playlist(FOLDER, parent_id=None, is_folder=True))
        print(f"created folder: {FOLDER}")

    existing = None
    for p in d.db.get_playlist():
        if (
            getattr(p, "rb_local_deleted", 0) == 0
            and p.Name == name
            and str(p.ParentID) == folder_id
        ):
            existing = str(p.ID)
            break
    if existing:
        tracks = await d.get_playlist_tracks(existing)
        if tracks:
            print(f"'{name}' already exists with {len(tracks)} tracks — leaving it alone.")
            await d.disconnect()
            return
        pl_id = existing
    else:
        pl_id = pid_of(await d.create_playlist(name, parent_id=folder_id, is_folder=False))

    ids = [r["track_id"] for r in rows]
    await d.add_tracks_to_playlist(pl_id, ids)
    got = await d.get_playlist_tracks(pl_id)
    print(f"\ncreated '{FOLDER} / {name}' — {len(got)} tracks "
          f"(order matches: {[str(t.id) for t in got] == ids})")
    await d.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
