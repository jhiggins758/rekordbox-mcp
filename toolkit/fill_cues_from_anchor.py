"""Fill the cue ladder from the anchor cue for every track in a playlist.

For each track that has the ANCHOR hot cue (per your mined cue_system), derive the
rest of your ladder and add any slots not already present. Never overwrites an
existing cue. This is the reliable post-import path: you set the anchor while
auditioning; this does the arithmetic.

Default DRY RUN. Pass --apply to write (rekordbox CLOSED; backup taken; adds go
through the same verified path as the MCP's add_track_cue).

    uv run --with numpy python toolkit/fill_cues_from_anchor.py [PlaylistName]
    uv run --with numpy python toolkit/fill_cues_from_anchor.py [PlaylistName] --apply
"""

import sys
import asyncio
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from djtk_config import load_config, open_db
from cue_model import beat_times_ms, ladder_from_anchor, cue_system, SLOT_TO_KIND

CFG = load_config()
args = [a for a in sys.argv[1:] if a != "--apply"]
PLAYLIST = args[0] if args else None
APPLY = "--apply" in sys.argv


def fmt_ms(ms):
    return f"{ms//60000}:{(ms % 60000)//1000:02d}.{ms % 1000:03d}"


async def main():
    cs = cue_system()
    anchor_kind = SLOT_TO_KIND[cs["anchor_slot"]]
    d = await open_db(CFG)
    from pyrekordbox.db6 import tables

    if PLAYLIST:
        pl = None
        for p in d.db.get_playlist():
            if getattr(p, "rb_local_deleted", 0) == 0 and (p.Name or "") == PLAYLIST:
                pl = p
                break
        assert pl is not None, f"playlist {PLAYLIST!r} not found"
        track_ids = [str(s.ContentID)
                     for s in d.db.get_playlist_songs(PlaylistID=pl.ID)
                     if getattr(s, "rb_local_deleted", 0) == 0]
        scope = f"playlist '{PLAYLIST}'"
    else:
        track_ids = None  # whole library
        scope = "whole library"

    cues_by_track = {}
    for c in d.db.query(tables.DjmdCue).all():
        if not (c.rb_local_deleted or 0):
            cues_by_track.setdefault(str(c.ContentID), []).append(c)

    ids = track_ids if track_ids is not None else list(cues_by_track)
    plan = []
    skipped = 0
    for tid in ids:
        cl = cues_by_track.get(tid, [])
        existing = {int(x.Kind or 0) for x in cl}
        if anchor_kind not in existing:
            skipped += 1
            continue
        content = d.db.get_content(ID=int(tid))
        if not content or getattr(content, "rb_local_deleted", 0) != 0:
            continue
        times = beat_times_ms(d.db, content)
        if times is None:
            skipped += 1
            continue
        a_cue = [x for x in cl if int(x.Kind or 0) == anchor_kind][0]
        a_beat = int(np.argmin(np.abs(times - int(a_cue.InMsec or 0))))
        _, ladder = ladder_from_anchor(content, times, a_beat, existing)
        adds = [(r["slot"], r["position_ms"]) for r in ladder
                if r["skip"] is None and r["position_ms"] is not None]
        if adds:
            plan.append((content, adds))

    total = sum(len(a) for _, a in plan)
    print(f"{'APPLY' if APPLY else 'DRY RUN'} — fill cue ladders in {scope}\n")
    print(f"tracks needing ladder fill: {len(plan)} | skipped (no anchor / no grid): {skipped}")
    print(f"cues to add: {total}\n")
    for c, adds in plan[:8]:
        slots = "  ".join(f"{s}@{fmt_ms(ms)}" for s, ms in adds)
        print(f"  {str(c.ID):>12} {(c.Title or '')[:34]:34s} {slots}")
    if len(plan) > 8:
        print(f"  ... and {len(plan) - 8} more")

    if not APPLY:
        print("\nDry run only — nothing written. Re-run with --apply (rekordbox CLOSED).")
        await d.disconnect()
        return

    added = 0
    for c, adds in plan:
        for slot, ms in adds:
            await d.add_track_cue(str(c.ID), ms, slot, overwrite=False, snap="none")
            added += 1
    print(f"\nAPPLIED: added {added} cues across {len(plan)} tracks.")
    await d.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
