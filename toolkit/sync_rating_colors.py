"""Sync rekordbox track Color to star Rating, per the config rating_colors mapping.

e.g. {"5": "Red", "4": "Orange", "3": "Yellow", "2": "Purple", "1": "Blue"} — unrated
tracks get NO color, so "no color" reliably means "not yet rated". Colors don't follow
automatically when you re-rate, so run this each refresh to catch drift.

Default is a DRY RUN (read-only, safe with rekordbox open) that reports drift.
Pass --apply to write (requires rekordbox CLOSED; takes a backup, one commit).
Prior colors are snapshotted to the workspace before every apply, so individual
assignments are recoverable without a full DB restore.

    uv run python toolkit/sync_rating_colors.py
    uv run python toolkit/sync_rating_colors.py --apply
"""
import asyncio, sys, json
from pathlib import Path
from collections import Counter

sys.path.insert(0, str(Path(__file__).parent))
from djtk_config import load_config, open_db, workspace

CFG = load_config()
_rc = CFG.get("rating_colors")
if not _rc:
    raise SystemExit("rating_colors not configured — set it in config.json to use this feature.")
MAP = {int(k): v for k, v in _rc.items()}
PRIOR = str(workspace(CFG, "prior_track_colors.json"))
APPLY = "--apply" in sys.argv


async def main():
    d = await open_db(CFG)

    colors = {str(c.ID): (c.Commnt or "").strip() for c in d.db.get_color()}
    cid_for = {}
    for r, name in MAP.items():
        c = d._resolve_color_by_name(name)
        assert c is not None, f"color {name!r} not defined in this database"
        cid_for[r] = str(c.ID)

    drift = Counter()          # rating -> tracks whose color is wrong/missing
    stale = []                 # unrated tracks still carrying a color
    examples = []
    for c in d.db.get_content():
        if getattr(c, "rb_local_deleted", 0) != 0:
            continue
        r = int(getattr(c, "Rating", 0) or 0)
        cur = colors.get(str(c.ColorID)) if c.ColorID else None
        if r in MAP:
            if cur != MAP[r]:
                drift[r] += 1
                if len(examples) < 10:
                    examples.append(f"{r}* {c.Title or '?'} — {cur or 'no color'} -> {MAP[r]}")
        elif cur:
            stale.append(c)

    total = sum(drift.values()) + len(stale)
    print(f"{'APPLY' if APPLY else 'DRY RUN'} — rating->color sync")
    for r in sorted(MAP, reverse=True):
        print(f"  {r}* -> {MAP[r]:6s}  out of sync: {drift[r]}")
    print(f"  unrated but colored (color will be cleared): {len(stale)}")
    print(f"  TOTAL out of sync: {total}")
    if examples:
        print("\n  examples:")
        for e in examples:
            print(f"    {e}")

    if not APPLY:
        print("\nDry run only — nothing written. Re-run with --apply (rekordbox must be CLOSED).")
    elif total == 0:
        print("\nAlready in sync — nothing to write.")
    else:
        prior = {str(c.ID): colors.get(str(c.ColorID))
                 for c in d.db.get_content()
                 if getattr(c, "rb_local_deleted", 0) == 0 and c.ColorID}
        json.dump(prior, open(PRIOR, "w", encoding="utf-8"), indent=1)
        d._create_backup()
        n = 0
        for c in d.db.get_content():
            if getattr(c, "rb_local_deleted", 0) != 0:
                continue
            r = int(getattr(c, "Rating", 0) or 0)
            target = cid_for[r] if r in MAP else None
            if str(c.ColorID or "") != (target or ""):
                c.ColorID = target
                n += 1
        d.db.commit()
        d._invalidate_content_cache()
        print(f"\nAPPLIED: {n} tracks recolored (one commit). Prior colors snapshotted to {PRIOR}")

    await d.disconnect()


asyncio.run(main())
