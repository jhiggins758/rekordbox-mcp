"""Find (and optionally tag) untagged tracks that credit a vocalist.

Two jobs, both important after importing music:
  1. REFRESH the stale `tagged_vocal` flag in the vocal features jsonl from the LIVE
     rekordbox tags. That flag is baked in at extract time and goes stale as the user
     tags more — leaving it stale makes vocal_calibrate surface already-tagged
     tracks as fake "candidates" (a measured failure mode in development).
  2. CREDIT SWEEP: the audio model misses ~26% of vocal tracks, so the reliable way
     to catch untagged vocal tracks is to scan credits for a named vocalist / feat.
     — NOT the audio score. This finds vocal tracks the Demucs pipeline never will.

In electronic music `feat.` is sometimes a PRODUCER collab (instrumental), so known
producers are excluded, as are tracks whose title says "(Instrumental)". Extend both
name lists via config vocal_names.extra_vocalists / .producers.

Default DRY RUN (also refreshes tagged_vocal — that write is workspace-only, safe with
rekordbox open). `--apply` adds your Vocal MyTag and needs rekordbox CLOSED.

    uv run python toolkit/find_vocal_credits.py [--family primary|secondary]
    uv run python toolkit/find_vocal_credits.py --apply
"""

import os
import re
import sys
import json
import asyncio
from uuid import uuid4
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from djtk_config import load_config, open_db, workspace, genre_match, tag_id
from pyrekordbox.db6 import tables

CFG = load_config()
FAMILY = "secondary" if "--family" in sys.argv and "secondary" in sys.argv else "primary"
VOCAL_TAG_ID = tag_id(CFG, "vocal")
FEATURES = str(workspace(CFG, f"vocal_features_{FAMILY}.jsonl"))
APPLY = "--apply" in sys.argv

# Named singers / MCs commonly credited on electronic tracks. A hit = vocal-forward.
# Extend per-library via config: vocal_names.extra_vocalists.
SINGERS = {
    "hayla", "charlotte haining", "sharlene hector", "emily makis", "poppy baskcomb", "koven",
    "katy b", "raphaella", "becky hill", "karen harding", "bebe rexha", "hayley may", "empara mi",
    "eva lazarus", "grace barton", "a little sound", "miss trouble", "mali-koa", "anna simone",
    "sarah de warren", "abi flynn", "aleya mae", "akacia", "cameron hayes", "julia church",
    "billy lockett", "nihils", "lauren l", "skyelle", "gracie van brunt", "stefflon don",
    "clementine douglas", "sammie hall", "reiki ruawai", "katie's ambition", "jazmine johnson",
    "fireboy dml", "stylo g", "holly", "elle exxe", "jozzy", "max marshall", "bettye lavette",
    "henry dell", "mira lu kovacs", "andrew hellier", "charlotte colley", "london thor",
    "darren styles", "reija lee", "brooke williams", "celldweller", "fairfields", "rezar",
    "b live", "innate mc", "eksman", "tom cane", "jem cooke", "ts graye", "takura", "flowdan",
    "stormzy", "backroad gee", "singing fats", "doktor", "cody frost", "starling", "cameron warren",
}
# DnB producers who appear after "feat." on instrumental collabs — a feat. of one of
# these (with no named singer) is NOT evidence of vocals.
PRODUCERS = {
    "dualistic", "dj marky", "bmotion", "dc breaks", "roni size", "replicant", "spor",
    "the prototypes", "sub killaz", "b motion", "t & sugah", "flowidus",
}
FEAT = re.compile(r"\bfeat\.?\b|\bft\.?\b|featuring|\(feat", re.I)
# per-library extensions from config
_vn = CFG.get("vocal_names") or {}
SINGERS |= {s.lower() for s in _vn.get("extra_vocalists") or []}
PRODUCERS |= {p.lower() for p in _vn.get("producers") or []}
# Word-boundary matchers so a name never matches inside another word
# (e.g. "holly" must not fire on "Hollywood").
SINGER_RE = re.compile(r"\b(" + "|".join(re.escape(s) for s in SINGERS) + r")\b", re.I)
PRODUCER_RE = re.compile(r"\b(" + "|".join(re.escape(p) for p in PRODUCERS) + r")\b", re.I)


def nm(row):
    return (getattr(row, "Name", "") if row else "") or ""


def refresh_tagged_flag(tagged):
    """Rewrite vocal_features.jsonl's tagged_vocal from the live tag set."""
    if not os.path.exists(FEATURES):
        return 0, 0
    rows = [json.loads(l) for l in open(FEATURES, encoding="utf-8") if l.strip()]
    changed = 0
    for r in rows:
        live = r["id"] in tagged
        if bool(r.get("tagged_vocal")) != live:
            changed += 1
        r["tagged_vocal"] = live
    open(FEATURES, "w", encoding="utf-8").write(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n"
    )
    return changed, sum(1 for r in rows if r["tagged_vocal"])


async def main():
    if not VOCAL_TAG_ID:
        raise SystemExit("No 'vocal' MyTag mapped in config tags — run dj-onboard first.")
    d = await open_db(CFG)

    tagged = set()
    for s in d.db.query(tables.DjmdSongMyTag):
        if getattr(s, "rb_local_deleted", 0) == 0 and str(s.MyTagID) == VOCAL_TAG_ID:
            tagged.add(str(s.ContentID))

    changed, now_tagged = refresh_tagged_flag(tagged)
    print(f"tagged_vocal refresh: updated {changed} rows in {os.path.basename(FEATURES)} "
          f"({now_tagged} now flagged tagged) | live Vocal tags: {len(tagged)}")

    hits = []
    for c in d.db.get_content():
        if getattr(c, "rb_local_deleted", 0) != 0:
            continue
        tid = str(c.ID)
        if tid in tagged:
            continue
        if not genre_match(CFG, FAMILY, nm(getattr(c, "Genre", None)), (c.BPM or 0) / 100.0):
            continue
        artist = nm(getattr(c, "Artist", None))
        title = c.Title or ""          # Title is a plain string, NOT a relationship row — do not nm() it
        low = f"{artist} {title}".lower()
        if "(instrumental)" in low:
            continue
        has_singer = bool(SINGER_RE.search(low))
        is_producer_feat = FEAT.search(title) and PRODUCER_RE.search(low) and not has_singer
        if is_producer_feat:
            continue
        if has_singer:
            hits.append((tid, artist, title, "named singer"))
        elif FEAT.search(title):
            hits.append((tid, artist, title, "feat. (assumed vocal)"))

    print(f"\n{'APPLY' if APPLY else 'DRY RUN'} — untagged {FAMILY} tracks crediting a vocalist: {len(hits)}\n")
    for tid, a, t, why in hits:
        print(f"  [{why:22}] {a} - {t}"[:96])

    if not APPLY:
        print("\nDry run — no Vocal tags written (tagged_vocal flag WAS refreshed, workspace-only).")
        print("Re-run with --apply (rekordbox CLOSED) to tag these.")
        await d.disconnect()
        return
    if not hits:
        await d.disconnect()
        return

    d._create_backup()

    def count_songtags(tid):
        return len([r for r in d._normalize_query_result(d.db.get_my_tag_songs(ContentID=str(tid)))
                    if getattr(r, "rb_local_deleted", 0) == 0])

    added = 0
    for tid, a, t, why in hits:
        now = datetime.now()
        d.db.add(tables.DjmdSongMyTag.create(
            ID=str(uuid4()), MyTagID=VOCAL_TAG_ID, ContentID=str(tid),
            TrackNo=count_songtags(tid) + 1, UUID=str(uuid4()), created_at=now, updated_at=now))
        added += 1
    d.db.commit()
    d._invalidate_content_cache()
    print(f"\nAPPLIED: added Vocal tag to {added} tracks (one commit).")
    await d.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
