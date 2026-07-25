"""Assign energy MyTags from star rating, per the config star_to_energy mapping.

Overlaps are allowed (a rating may grant two tags, e.g. 4 stars -> Medium AND High).

Scope: new/untagged only. A track that already carries ANY mapped energy tag is left
completely alone (it may be a hand-placed call). Only rated tracks with no energy
tag at all get tagged. Additive, one backup, one commit.

Default is a DRY RUN (read-only, safe with rekordbox open). Pass --apply to write
(rekordbox must be CLOSED).

    uv run python toolkit/assign_energy_tags.py
    uv run python toolkit/assign_energy_tags.py --apply
"""

import sys
import asyncio
from uuid import uuid4
from datetime import datetime
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from djtk_config import load_config, open_db, tag_id
from pyrekordbox.db6 import tables

CFG = load_config()
LEVELS = ("low", "medium", "high")
LEVEL_TAG = {lv: tag_id(CFG, f"energy_{lv}") for lv in LEVELS}
missing = [lv for lv, t in LEVEL_TAG.items() if not t]
if missing:
    raise SystemExit(f"No MyTag mapped for energy level(s) {missing} in config tags — run dj-onboard.")
ENERGY_IDS = set(LEVEL_TAG.values())
NAME = {t: f"{lv.capitalize()} Energy" for lv, t in LEVEL_TAG.items()}

# star rating -> energy tag ids to add (from config star_to_energy)
RATING_TAGS = {}
for star, levels in (CFG.get("star_to_energy") or {}).items():
    RATING_TAGS[int(star)] = [LEVEL_TAG[lv] for lv in levels if lv in LEVEL_TAG]

APPLY = "--apply" in sys.argv


async def main():
    d = await open_db(CFG)

    tag_name = {
        str(t.ID): t.Name
        for t in d.db.get_my_tag()
        if getattr(t, "rb_local_deleted", 0) == 0
    }
    for tid in ENERGY_IDS:
        assert tid in tag_name, f"configured energy tag id {tid} not found in this library's MyTags"

    # every track's current energy tags
    energy_of = {}
    for s in d.db.query(tables.DjmdSongMyTag):
        if getattr(s, "rb_local_deleted", 0) == 0 and str(s.MyTagID) in ENERGY_IDS:
            energy_of.setdefault(str(s.ContentID), set()).add(str(s.MyTagID))

    active = [c for c in d.db.get_content() if getattr(c, "rb_local_deleted", 0) == 0]

    plan = []  # (content_id, [tag_ids])
    skipped_has_energy = skipped_unrated = 0
    add_counts = Counter()
    for c in active:
        tid = str(c.ID)
        rating = int(getattr(c, "Rating", 0) or 0)
        if rating == 0:
            skipped_unrated += 1
            continue
        if tid in energy_of:  # already has an energy tag -> leave alone
            skipped_has_energy += 1
            continue
        tags = RATING_TAGS.get(rating)
        if not tags:
            continue
        plan.append((tid, tags))
        for t in tags:
            add_counts[t] += 1

    print(f"{'APPLY' if APPLY else 'DRY RUN'} — energy tags from star rating\n")
    print(f"active tracks: {len(active)}")
    print(f"  skipped, no rating         : {skipped_unrated}")
    print(f"  skipped, already has energy: {skipped_has_energy}")
    print(f"  tracks to tag              : {len(plan)}")
    print("\n  tag assignments to add:")
    for lv in LEVELS:
        t = LEVEL_TAG[lv]
        print(f"    {NAME[t]:14s}: {add_counts[t]}")

    if not APPLY:
        print("\nDry run only — nothing written. Re-run with --apply (rekordbox CLOSED).")
        await d.disconnect()
        return
    if not plan:
        print("\nNothing to tag.")
        await d.disconnect()
        return

    d._create_backup()

    def count_songtags(tid):
        return len(
            [
                r
                for r in d._normalize_query_result(d.db.get_my_tag_songs(ContentID=str(tid)))
                if getattr(r, "rb_local_deleted", 0) == 0
            ]
        )

    added = 0
    for tid, tags in plan:
        base = count_songtags(tid)
        for i, mytag_id in enumerate(tags):
            now = datetime.now()
            row = tables.DjmdSongMyTag.create(
                ID=str(uuid4()),
                MyTagID=mytag_id,
                ContentID=str(tid),
                TrackNo=base + 1 + i,
                UUID=str(uuid4()),
                created_at=now,
                updated_at=now,
            )
            d.db.add(row)
            added += 1

    d.db.commit()
    d._invalidate_content_cache()
    print(f"\nAPPLIED: added {added} energy tags to {len(plan)} tracks (one commit).")
    await d.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
