# Changelog

## 2026-07 — DJ Toolkit + cue points release

### Added — MCP server
- **Cue point tools** (`get_track_cues`, `add_track_cue`, `update_track_cue`,
  `delete_track_cue`) with beat-grid snapping (`beat` / `downbeat` / `phrase` / `none`),
  occupied-slot protection, soft deletes, and dual-representation writes (`djmdCue` +
  `contentCue` JSON mirror). Slot mapping verified by UI round-trip (A=1…H=9, Kind 4
  reserved, Kind 0 = memory cue).
- **`get_track_beatgrid`** — beats, downbeats, and 8-bar phrase starts from ANLZ data.
- **Track metadata tools** — `set_track_rating`, `set_track_color`, `set_track_comment`,
  `add_track_my_tag`, `remove_track_my_tag`, `get_my_tags`, `get_track_my_tags`,
  `get_available_colors`.
- **Track import tools** — `import_track`, `import_tracks` (ID3 autofill via mutagen,
  Artist/Album/Genre/Label rows created on demand).
- Test suite: 160+ tests, mocked pyrekordbox (incl. 47 cue tests).

### Added — DJ Toolkit (`toolkit/` + `skills/`)
- Config-driven workflow layer: `djtk_config.py` + `config.example.json` (per-library
  MyTag mapping, genre families, star→energy, music roots, cue system, preferences).
- `mine_cue_system.py` — discovers the user's hot-cue anchor + per-genre offset ladders
  from their existing cues, with per-slot consistency tiers (core / optional).
- `cue_model.py` / `fill_cues_from_anchor.py` — ladder derivation from a user-placed
  anchor; audio drop-detection fallback (heuristic or trained ranker).
- Auto-cue ML chain: `cue_extract.py`, `cue_train.py` (LambdaMART / gradient boosting on
  the user's own cues), `cue_confidence.py` (calibrated confidence tiers),
  `cue_batch.py`, `cue_review_playlist.py`.
- Audio character pipeline: `extract_features.py`, `calibrate.py` (melodic-vs-heavy
  fitted against the user's tags).
- Vocal pipeline: `find_vocal_credits.py` (credit sweep — primary signal),
  `vocal_extract.py` (Demucs stem separation), `vocal_calibrate.py` (user tags
  authoritative; audio suggests only).
- Metadata utilities: `assign_energy_tags.py` (star→energy), `sync_rating_colors.py`.
- Claude Code skills: `dj-onboard` (setup wizard), `cue-tracks`, `process-imports`,
  `refresh-dj-engine`.
- `docs/FIELD_NOTES.md` — empirical rekordbox DB knowledge (relinking, cue internals,
  ORM traps, smart playlists, honest audio-analysis limits).

### Fixed
- `connect()` now honors an explicit database path correctly (pyrekordbox selects the DB
  file via `path=`, not `db_dir=`) and backups land beside the connected database.
- Active-row filters treat freshly-created ORM rows (`rb_local_deleted=None` pre-flush)
  as active.

## Earlier (upstream base)
- Fork of [davehenke/rekordbox-mcp](https://github.com/davehenke/rekordbox-mcp):
  search/discovery, playlists (incl. folders), DJ history, library analytics, cleanup
  tools, genre search.
