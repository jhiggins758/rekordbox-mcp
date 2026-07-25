"""Discover YOUR hot-cue system by mining the cues you've already placed.

Most working DJs cue consistently without ever writing the system down — e.g. one
slot always sits on the drop and the others count down fixed numbers of bars
before it. This script rediscovers that structure from your library so the cue
tools can replicate it on uncued tracks:

  1. Which slots you use, and how often (per rekordbox slot letter)
  2. Which slot is your ANCHOR — the one every other slot is positioned relative to
     (detected: the slot whose relative offsets are most consistent across tracks)
  3. Your per-genre LADDER: the modal offset (in beats) of each slot from the
     anchor, with a hit-rate showing how consistently you place it

Reads beat grids from the rekordbox analysis files, so offsets are in musical
beats, not milliseconds. Read-only; safe with rekordbox open.

    uv run --with numpy python toolkit/mine_cue_system.py            # report only
    uv run --with numpy python toolkit/mine_cue_system.py --write    # also save to config

Needs ≥ ~50 cued tracks for a trustworthy ladder; below that it reports what it
sees and recommends manual-anchor mode. (Method validated on a 2,600-track
library: rediscovered the owner's full ladder with 91-99% per-slot consistency.)
"""

import sys
import asyncio
from collections import Counter, defaultdict

import numpy as np

sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))
from djtk_config import load_config, open_db, save_config, genre_match

from pyrekordbox.db6 import tables

# rekordbox hot-cue slots: DjmdCue.Kind -> slot letter (Kind 4 is reserved; 0 = memory cue)
KIND_TO_SLOT = {1: "A", 2: "B", 3: "C", 5: "D", 6: "E", 7: "F", 8: "G", 9: "H"}
SLOT_TO_KIND = {v: k for k, v in KIND_TO_SLOT.items()}
MIN_TRACKS = 50
WRITE = "--write" in sys.argv


def beat_times_ms(db, content):
    """Beat grid in ms from the ANLZ .DAT. Avoids pyrekordbox's AnlzFile
    __len__/__contains__ recursion bug: use tag_types and `is None` only."""
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


async def main():
    cfg = load_config()
    d = await open_db(cfg)
    db = d.db

    cues_by_track = defaultdict(list)
    for c in db.query(tables.DjmdCue).all():
        if not (c.rb_local_deleted or 0):
            cues_by_track[str(c.ContentID)].append(c)

    def nm(row):
        return (getattr(row, "Name", "") if row else "") or ""

    families = list((cfg.get("genres") or {"primary": None}).keys())

    # beat-index every cued track (per genre family)
    per_family = defaultdict(list)  # family -> list of {slot: beat_index}
    slot_use = Counter()
    n_cued = 0
    for tid, cues in cues_by_track.items():
        content = db.get_content(ID=int(tid))
        if content is None or (content.rb_local_deleted or 0):
            continue
        n_cued += 1
        hot = {}
        for cu in cues:
            k = int(cu.Kind or 0)
            if k in KIND_TO_SLOT:
                slot_use[KIND_TO_SLOT[k]] += 1
                hot[KIND_TO_SLOT[k]] = int(cu.InMsec or 0)
        if len(hot) < 2:
            continue
        genre = nm(getattr(content, "Genre", None))
        bpm = (content.BPM or 0) / 100.0
        fam = next((f for f in families if genre_match(cfg, f, genre, bpm)), None)
        if fam is None:
            continue
        times = beat_times_ms(db, content)
        if times is None or len(times) < 64:
            continue
        beats = {s: int(np.argmin(np.abs(times - ms))) for s, ms in hot.items()}
        per_family[fam].append(beats)

    print(f"cued tracks: {n_cued}")
    print("slot usage:", dict(slot_use.most_common()))
    usable = sum(len(v) for v in per_family.values())
    print(f"tracks usable for mining (>=2 hot cues, known genre family, beat grid): {usable}\n")
    if usable < MIN_TRACKS:
        print(f"Fewer than {MIN_TRACKS} usable tracks — not enough signal for a reliable "
              f"ladder. Recommendation: keep cue_system null (manual-anchor mode) and re-run "
              f"after you've cued more tracks.")
        await d.disconnect()
        return

    # ANCHOR detection: for each candidate slot, how consistent are the OTHER
    # slots' offsets relative to it? Score = mean over slots of (mode share).
    all_tracks = [b for v in per_family.values() for b in v]
    candidates = [s for s, n in slot_use.items() if n >= usable * 0.5]
    anchor_scores = {}
    for anchor in candidates:
        shares = []
        for slot in KIND_TO_SLOT.values():
            offs = [b[slot] - b[anchor] for b in all_tracks if anchor in b and slot in b and slot != anchor]
            if len(offs) < 20:
                continue
            mode, count = Counter(offs).most_common(1)[0]
            shares.append(count / len(offs))
        if shares:
            anchor_scores[anchor] = float(np.mean(shares))
    if not anchor_scores:
        print("Could not evaluate any anchor candidate — not enough co-occurring slots.")
        await d.disconnect()
        return
    anchor = max(anchor_scores, key=anchor_scores.get)
    print("anchor-candidate consistency:",
          {s: round(v, 3) for s, v in sorted(anchor_scores.items(), key=lambda x: -x[1])})
    print(f"=> ANCHOR slot: {anchor} (every other slot positioned relative to it)\n")

    # Per-family ladders relative to the anchor. Slots with >=85% exact placement
    # are CORE (you place them essentially always when there's room — fill tools
    # treat missing core slots as work to do); 35-85% are optional (offered, not
    # assumed); below 35% aren't shipped at all.
    ladders = {}
    core = {}
    for fam, rows in per_family.items():
        print(f"--- {fam} (n={len(rows)}) — offsets in beats from {anchor} "
              f"(negative = before) ---")
        ladder = {}
        fam_core = []
        for slot in KIND_TO_SLOT.values():
            if slot == anchor:
                continue
            offs = [b[slot] - b[anchor] for b in rows if anchor in b and slot in b]
            if len(offs) < 10:
                continue
            mode, count = Counter(offs).most_common(1)[0]
            share = count / len(offs)
            near = sum(1 for o in offs if abs(o - mode) <= 2) / len(offs)
            tier = "CORE" if share >= 0.85 else ("optional" if share >= 0.35 else "dropped")
            print(f"  {slot}: n={len(offs):4d}  mode {mode:+5d} beats ({mode/4:+6.1f} bars)  "
                  f"exact {share:5.1%}  within±2 {near:5.1%}  [{tier}]")
            if share >= 0.35:
                ladder[slot] = int(mode)
            if share >= 0.85:
                fam_core.append(slot)
        if ladder:
            ladders[fam] = dict(sorted(ladder.items(), key=lambda kv: kv[1]))
            core[fam] = sorted(fam_core)
        print()

    proposal = {"anchor_slot": anchor, "anchor_meaning": "(confirm: e.g. 'the drop')",
                "ladders": ladders, "core_slots": core}
    print("proposed cue_system config block:")
    import json as _json
    print(_json.dumps(proposal, indent=1))

    if WRITE:
        cfg["cue_system"] = proposal
        save_config(cfg)
        print(f"\nwritten to {cfg['_path']}")
    else:
        print("\n(re-run with --write to save into your config)")
    await d.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
