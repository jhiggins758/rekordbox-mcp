# DJ Toolkit — setup (Claude Code)

This is the **workflow layer** for `rekordbox-mcp`: audio-analysis pipelines and Claude
Code skills that learn *your* conventions (your MyTags, your hot-cue system, your star
ratings) and drive them conversationally. It is self-contained — it ships its own copy of
the MCP server, so you do **not** need the `.mcpb` (that one is for Claude Desktop; this
one is for Claude Code).

**Design principle: your data is ground truth.** Your tags beat audio models, your existing
cues define your cue system, your ratings define energy. Audio analysis only fills gaps and
only ever *proposes* — every write is approval-gated.

## Prerequisites

- **[`uv`](https://docs.astral.sh/uv/)** on your PATH
  ```bash
  # macOS / Linux
  curl -LsSf https://astral.sh/uv/install.sh | sh
  # Windows (PowerShell)
  powershell -c "irm https://astral.sh/uv/install.ps1 | iex"
  ```
- **Claude Code** installed (`npm i -g @anthropic-ai/claude-code`).
- **rekordbox 6 or 7** with an existing library. Read-only steps work with rekordbox open;
  anything that writes needs it **closed** (pyrekordbox blocks commits while it runs).
- Back up your rekordbox library first. The toolkit also takes its own timestamped DB
  backup before every write, but keep your own too.

## Install

1. **Unzip** this bundle somewhere permanent (its path gets referenced below):
   ```bash
   unzip rekordbox-dj-toolkit.zip -d ~/rekordbox-dj-toolkit
   cd ~/rekordbox-dj-toolkit
   ```

2. **Resolve the environment** (installs pyrekordbox, numpy, and the bundled server):
   ```bash
   uv sync
   ```

3. **Register the MCP server with Claude Code** so the skills can reach your library.
   Point it at this bundle directory:
   ```bash
   claude mcp add rekordbox -- uv run --directory "$(pwd)" rekordbox-mcp
   ```
   (Add `--database-path /path/to/Pioneer` after `rekordbox-mcp` only if auto-detect can't
   find your `master.db`.)

4. **Install the skills** into Claude Code:
   ```bash
   mkdir -p ~/.claude/skills
   cp -r skills/dj-onboard skills/cue-tracks skills/process-imports skills/refresh-dj-engine ~/.claude/skills/
   ```
   Restart your Claude Code session so it picks them up.

## First run

In Claude Code, run the onboarding wizard:

```
/dj-onboard
```

It connects to your database, maps your MyTags, learns your star-rating → energy mapping,
**mines your personal hot-cue system** from cues you've already placed, and writes
`~/.dj-toolkit/config.json`. Everything the toolkit does afterward is driven by that file —
nothing is hardcoded to anyone else's library. Re-run it any time to update the config.

Then drive the workflows conversationally with the other skills:
- **`cue-tracks`** — fill hot-cue ladders (you set one anchor cue; the toolkit derives the rest).
- **`process-imports`** — cues + energy tags + vocal tags for freshly imported tracks.
- **`refresh-dj-engine`** — periodic maintenance: rating→color sync, energy tags, feature refresh.

## Optional heavy pipelines

Two analyses are opt-in and slower; the onboarding offers them but never runs them for you:
- `extract_features.py` — ~1–2 s/track; enables the melodic-vs-heavy character model
  (`uv run --with numpy --with librosa python toolkit/extract_features.py`).
- `vocal_extract.py` — ~15–20 s/track on CPU (hours for a large library); adds an audio
  *suggestion* for vocal tracks. Both are resumable.

Your workspace (features, models, reports) is written to the directory named in your config —
never into your rekordbox library or this bundle.

## Where things are

- `toolkit/` — the scripts, all configured via `~/.dj-toolkit/config.json` (see
  `toolkit/config.example.json`).
- `skills/` — the Claude Code skills.
- `docs/FIELD_NOTES.md` — hard-won rekordbox database internals (relinking, cue internals,
  ORM traps, smart playlists). Read this before touching database behavior.
- `rekordbox_mcp/` — the bundled MCP server (same code as the `.mcpb`), so this bundle is
  self-contained.
