---
name: process-imports
description: Finish newly imported rekordbox tracks after the user sets their anchor cue + star rating on each — fill the cue ladder from the anchor, assign energy MyTags from star ratings, and tag vocal tracks. All DB mutations; rekordbox must be CLOSED. Use after the user imports music and says they've set anchors and ratings.
---

# Process Imports

Runs after the user imports new tracks and has, in rekordbox, set their ANCHOR hot cue and
star rating on each new track (that's the human part — everything below is derivable).
Read `~/.dj-toolkit/config.json` first for tag IDs, star mapping and the cue system.

All steps **mutate the rekordbox database** → rekordbox must be **CLOSED** (check the
rekordbox app process names; never match the MCP server's own process). Every script takes
a backup and commits once. Every step is **dry-run by default**; present the dry run and
get an OK before `--apply`.

## Step 1 — Fill cue ladders from their anchors
```
uv run --with numpy python toolkit/fill_cues_from_anchor.py [ImportPlaylist]
uv run --with numpy python toolkit/fill_cues_from_anchor.py [ImportPlaylist] --apply
```
~99% faithful arithmetic on their mined ladder. Do NOT run audio drop-detection on tracks
that already have an anchor. Skips occupied slots, never overwrites.

## Step 2 — Energy tags from star ratings
```
uv run python toolkit/assign_energy_tags.py            # dry run
uv run python toolkit/assign_energy_tags.py --apply
```
Uses config `star_to_energy` (overlaps allowed). Scope is untagged-only: a track already
carrying any mapped energy tag is left alone (it may be a hand-placed call). ⚠️ The FIRST
apply also back-fills every older rated-but-untagged track, not just new imports — show the
dry-run counts and confirm the user wants the backlog done.

## Step 3 — Vocal tagging (credit sweep first, audio second)
```
uv run python toolkit/find_vocal_credits.py            # dry run + refreshes stale flags
uv run python toolkit/find_vocal_credits.py --apply
```
Credits (named vocalist / "feat.") are the RELIABLE vocal signal; audio models under-detect
(~26% false negatives measured). Present the found list; note MC-only features separately
(MC chatter clashes less in a mix than sung vocals — the user decides those). If they name
a vocalist the sweep didn't know, add it to config `vocal_names.extra_vocalists`.
Optional audio pass for uncredited hooks: `vocal_extract.py` (slow) + `vocal_calibrate.py`
— its untagged high-scorers are review candidates, never auto-tagged.

## Step 4 — Optional finishing
- `sync_rating_colors.py` if `rating_colors` is configured
- Offer `/refresh-dj-engine` so audio features/character cover the new tracks

## Report
Per step: counts from the dry run, what was applied, anything skipped and why.
