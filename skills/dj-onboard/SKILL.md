---
name: dj-onboard
description: One-time setup wizard for the rekordbox DJ toolkit. Connects to the user's rekordbox database via the MCP, maps their MyTags, learns their star-rating conventions, mines their personal hot-cue system from their existing cues, and writes the toolkit config. Run once after installing the rekordbox-mcp server, or re-run to update the config.
---

# DJ Toolkit Onboarding

Set up this workstation so the cue-tracks / process-imports / refresh-dj-engine skills work
on the USER'S library and conventions — nothing is assumed from anyone else's setup.

Principle for the whole toolkit: **the user's own data is ground truth.** Their tags beat
audio models; their existing cues define the cue system; their ratings define energy. Audio
analysis only fills gaps and only ever *suggests*.

## Steps

### 1. Verify the MCP connection
Call `database_status` / `connect_database`. If auto-detect fails, ask where rekordbox's
`master.db` lives (the folder, e.g. `D:/PIONEER/Master`) and pass it to `connect_database`.
rekordbox may be OPEN for everything in this onboarding — it's all read-only on the DB.

### 2. Create the config
Copy `toolkit/config.example.json` to `~/.dj-toolkit/config.json` (create the folder).
Record `database_dir` (null if auto-detect worked). All later steps edit this file.

### 3. Map their MyTags
Call `get_my_tags` and show the tag tree. Then ask (AskUserQuestion, one call):
- Which tag (if any) marks **vocal** tracks? → `tags.vocal`
- Which tags mean **low / medium / high energy**? → `tags.energy_low/medium/high`
- A **favorite/anthem** tag? → `tags.favorite`
- Any tags whose tracks should be **ignored** by set/cue tools? → `tags.ignore`
- Which tag NAMES describe **melodic/light** vs **heavy/dark** character? → `character_tags`
Record the IDs (tags are per-database; never reuse another library's IDs). Any role can be
"none" — dependent features degrade gracefully.

### 4. Genres, ratings, files
Ask:
- Their main performing genre(s) + BPM ranges → `genres.primary` (and `.secondary`).
  Offer to compute the library's genre/BPM distribution first so they choose from reality.
- How star ratings map to energy → `star_to_energy` (overlaps allowed, e.g. 4★ → medium+high).
- Folders where their audio files live → `music_roots` (needed for audio analysis).
- Optional: rating→color scheme → `rating_colors` (else null).

### 5. Mine their cue system  ⭐ the signature step
```
uv run --with numpy python toolkit/mine_cue_system.py
```
Present the result: detected anchor slot, per-genre ladder offsets, and per-slot consistency
percentages. Ask the user to CONFIRM the anchor's meaning ("is your C cue the drop?") and the
ladder before writing with `--write`. Hit-rates below ~85% mean that slot is optional for
them — the report already tiers this.
- **If <50 usable cued tracks**: skip, leave `cue_system` null, and explain that cue tools
  will run in manual-anchor mode until they've cued more tracks and re-run the miner.

### 6. Offer (never auto-run) the heavy pipelines
- `extract_features.py` — ~1-2s/track; enables the character model
- `vocal_extract.py` — ~15-20s/track on CPU (hours for large libraries); enables vocal
  classification. Both resumable. Warn about runtimes and let the user decide when.

### 7. Install the skills
Tell the user to copy `skills/cue-tracks`, `skills/process-imports`, and
`skills/refresh-dj-engine` into `~/.claude/skills/` and restart their session.

## Report
Summarize the written config: mapped tags, genre families, star mapping, mined cue system
(anchor + ladders + consistency), and which optional pipelines were run or deferred.
