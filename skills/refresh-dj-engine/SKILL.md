---
name: refresh-dj-engine
description: Re-index the DJ toolkit after adding music to rekordbox — extract audio features for new tracks, recalibrate the character model, refresh vocal data (credit sweep + optional Demucs), and sync rating colors. Mostly read-only on the rekordbox DB (safe with rekordbox open); tag/color writes are separate opt-in steps. Run whenever new tracks are imported.
---

# Refresh DJ Engine

Keeps the toolkit's derived data current with the library. Read
`~/.dj-toolkit/config.json` first. Everything below reads the rekordbox DB and writes only
to the workspace — safe with rekordbox open — EXCEPT the explicitly-marked `--apply` steps.

## Steps (in order, report after each)

1. **Audio features (new tracks only — resumable).**
   ```
   uv run --with librosa --with soundfile --with numpy python toolkit/extract_features.py
   ```
   ~1-2s per new track; skips tracks already done. If new tracks report `skipped (no
   file)`, their audio isn't under any configured `music_roots` — ask the user.

2. **Recalibrate the character model.**
   ```
   uv run --with scikit-learn --with numpy python toolkit/calibrate.py
   ```
   Fits melodic-vs-heavy within the primary genre family against the user's own
   `character_tags`. Report the CV accuracy and the "MISLABELED SUSPECTS" list (tagged
   melodic, audio says harsh) as re-tag candidates — offer, don't auto-apply.
   ⚠️ Known limit: the audio score does NOT reliably capture what a DJ means by "heavy"
   (measured). It's a soft signal; the user's tags and stated artist preferences outrank it.

3. **Vocal refresh — credit sweep is primary.**
   ```
   uv run python toolkit/find_vocal_credits.py           # dry run; also refreshes stale flags
   ```
   This BOTH refreshes the stale `tagged_vocal` flags from live tags (skipping this makes
   step 3b invent already-tagged "candidates") AND finds untagged tracks crediting a
   vocalist. Present finds; `--apply` to tag needs rekordbox CLOSED + user OK.

   3b. *(Optional, slow)* Demucs audio pass for uncredited hooks:
   ```
   uv run --with demucs --with librosa --with soundfile --with numpy python toolkit/vocal_extract.py
   uv run --with numpy python toolkit/vocal_calibrate.py
   ```
   Tagged tracks are level 2 by the user's tag (authoritative); audio only SUGGESTS
   candidates for untagged tracks. Manual overrides in config survive recalibration.

4. **Rating-color sync (if `rating_colors` configured).**
   ```
   uv run python toolkit/sync_rating_colors.py           # dry run
   ```
   Report drift; offer `--apply` (rekordbox CLOSED). Also clears colors from tracks that
   lost their rating, keeping "no color = unrated" true.

5. **Cue-system upkeep.** If the user has cued many new tracks since onboarding, offer to
   re-run `mine_cue_system.py` (their ladder statistics sharpen with more data) and, if
   the auto-cue ranker is in use, to re-run `cue_extract.py` + `cue_train.py` +
   `cue_confidence.py` so it learns from the new anchors.

## Report
New tracks featurized · character model CV + suspects · vocal finds (tagged or deferred) ·
color drift · whether cue mining/ranker retraining is worth running.
