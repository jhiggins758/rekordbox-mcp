---
name: cue-tracks
description: Propose and apply hot cues on uncued rekordbox tracks, following the USER'S own cue system (mined from their existing cues by dj-onboard). The reliable path derives the full ladder from an anchor cue the user sets; an audio drop-detection fallback exists for bulk work but always requires approval. Use when the user wants tracks cued or asks what's missing cues.
---

# Cue Tracks

Fill in hot cues the way THIS user cues, not a generic layout. Read
`~/.dj-toolkit/config.json` first — `cue_system` holds their mined anchor slot and
per-genre ladders (offsets in beats). If `cue_system` is null, only manual-anchor mode is
available; suggest re-running `mine_cue_system.py` once they've cued ~50+ tracks.

Their system, conceptually: one ANCHOR slot has a musical meaning (commonly "the drop"),
and every other slot sits a fixed number of beats from it. Confirmed pattern: deriving the
ladder from a user-placed anchor is ~99% faithful; detecting the anchor from audio is NOT
(~55-65% beat-perfect at best). So:

## Preferred workflow: user sets the anchor, toolkit fills the ladder
The user marks only the anchor cue in rekordbox while auditioning (they're never wrong
about their own drop), then:
```
uv run --with numpy python toolkit/cue_model.py --scan-from-anchor      # who's waiting
uv run --with numpy python toolkit/cue_model.py --from-anchor <id>      # one track's ladder
uv run --with numpy python toolkit/fill_cues_from_anchor.py [Playlist]  # batch dry-run
uv run --with numpy python toolkit/fill_cues_from_anchor.py [Playlist] --apply
```
Present the dry run, get approval, then `--apply` (rekordbox CLOSED). Never overwrite an
existing cue; skip occupied slots and report them.

## Fallback: audio drop detection (approval-gated, never bulk-applied)
For tracks with no anchor at all:
```
uv run --with librosa --with soundfile --with scikit-learn --with numpy \
    python toolkit/cue_model.py --propose <id>
```
Uses the trained ranker when `workspace/cue_ranker.pkl` exists (train it on THIS user's
cues: `cue_extract.py` then `cue_train.py`, then calibrate confidence tiers with
`cue_confidence.py`), else a spectral heuristic. **Always show the detected drop time
first** — if the drop is wrong, every cue is wrong — plus the alternates (the right answer
is usually in the top 3). Batch mode: `cue_batch.py [N]` groups proposals by confidence
tier; `cue_review_playlist.py` builds a review playlist ordered high→low confidence so the
user can audition in rekordbox (order carries the tier — tell them which positions are
which). High tier → skim & approve; low tier → don't waste their review time, route those
to set-the-anchor-yourself.

## Applying cues
Through the MCP `add_track_cue` tool or `fill_cues_from_anchor.py --apply`. Rules:
- rekordbox must be **CLOSED** for writes (verify the process; match the rekordbox app
  process names, never the MCP server's own process)
- backups are automatic; deletes are soft; occupied slots refuse unless the user
  explicitly asks to overwrite
- positions snap to the beat grid by default

## Corrections train the system
If the user says a proposed drop is off, ask by how much **in bars** (DJs think in
measures), re-derive the whole ladder from the corrected anchor — don't nudge cues
individually. Every anchor they place is future training data for the ranker.
