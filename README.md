# Rekordbox MCP Server

A comprehensive Model Context Protocol (MCP) server for rekordbox database management with real-time database access.

**Built using [pyrekordbox](https://github.com/dylanljones/pyrekordbox)** - This project is not affiliated with the pyrekordbox project or its maintainers.

<a href="https://glama.ai/mcp/servers/@davehenke/rekordbox-mcp">
  <img width="380" height="200" src="https://glama.ai/mcp/servers/@davehenke/rekordbox-mcp/badge" alt="rekordbox-mcp MCP server" />
</a>

## Features

### 🗄️ Database Access
- **Direct SQLite Database Connection**: Access the encrypted rekordbox database directly using pyrekordbox
- **Real-time Queries**: Search and filter tracks with comprehensive criteria
- **Safe Mutation Operations**: Playlist management with automatic backups and safety annotations

### 🔍 Search & Discovery
- **Advanced Search**: Multi-field search across artist, title, genre, key, BPM, and more
- **Musical Key Filtering**: Find tracks in compatible keys for harmonic mixing
- **BPM Range Queries**: Search by tempo ranges for beatmatching
- **Rating and Play Count Filters**: Discover your most loved and most played tracks

### 📊 Analytics & Insights
- **Library Statistics**: Comprehensive stats including genre distribution, average BPM, total playtime
- **Play Count Analytics**: Track listening patterns and habits
- **Collection Insights**: Understand your music library composition
- **DJ History Access**: Full access to your DJ session history and performance data

### ⚙️ Database Operations
- **Playlist Management**: Create, modify, and delete playlists with safety protections
- **Batch Operations**: Add multiple tracks to playlists efficiently
- **History Analysis**: Access complete DJ session history and performance data
- **Library Statistics**: Comprehensive analytics and insights

## Architecture

- **FastMCP Framework**: Modern Python MCP server using FastMCP 2.0
- **pyrekordbox Integration**: Mature library for encrypted database access
- **Real-time Database Queries**: Direct SQLite operations with SQLCipher support
- **Production Ready**: Built-in logging, error handling, and safety features

## ⚠️ Important Safety Notice

**BACKUP YOUR REKORDBOX LIBRARY BEFORE USE**

This software directly accesses your rekordbox database. **Always create a backup** of your entire rekordbox library before using this tool as a precautionary measure.

### Backup Requirements

**You should create a complete backup of your rekordbox library before using this software.** Consult rekordbox documentation or support resources for proper backup procedures for your specific setup and rekordbox version.

### Risk Acknowledgment

- ⚠️ **This project accesses your rekordbox database directly**
- ⚠️ **Use at your own risk - no warranty provided**  
- ⚠️ **Test thoroughly with backups before using on your main library**
- ⚠️ **The developers are not responsible for any data loss or damage**

**If you are not comfortable with these risks, use the read-only XML export functionality instead.**

## Install into Claude Desktop (one file)

The easiest way to install — no cloning, no editing JSON:

1. Download the latest **`rekordbox-mcp.mcpb`** from the
   [Releases page](https://github.com/jhiggins758/rekordbox-mcp/releases/latest).
2. Open **Claude Desktop → Settings → Extensions**.
3. **Drag the `.mcpb` file** into the Extensions window (or use *Install from file*).
4. (Optional) Set your **Rekordbox database folder** in the extension's settings — the
   folder containing `master.db`. Leave it blank to auto-detect the default install
   location.
5. Enable the extension.

**Prerequisite — [`uv`](https://docs.astral.sh/uv/) must be installed and on your PATH.**
The bundle ships the server's source and launches it with `uv`, which resolves Python and
the correct native dependencies (SQLCipher, numpy, …) per platform on first run:

```bash
# macOS / Linux
curl -LsSf https://astral.sh/uv/install.sh | sh
# Windows (PowerShell)
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"
```

Notes:
- **rekordbox 6 or 7** with an existing library is required. The database encryption key is
  fetched automatically by pyrekordbox on first connect; if a machine can't auto-resolve it,
  run the `setup-key.py` fallback shipped in the bundle.
- **First launch takes ~1–2 minutes** while `uv` builds the dependency environment. If the
  first handshake times out, disable and re-enable (or restart) the extension once.
- **Write tools require rekordbox to be closed** (pyrekordbox blocks commits while it runs);
  read-only tools work with it open. Back up your library first (see safety notice above).
- The **DJ Toolkit** (`toolkit/` + `skills/`) is a separate optional install — see
  [The DJ Toolkit](#the-dj-toolkit-optional--toolkit--skills) below.

## Quick Start

### Prerequisites
- Python 3.12+
- rekordbox 6 or 7 installed with an existing library
- **COMPLETE BACKUP** of your rekordbox library (see safety notice above)
- **Read-only tools** (search, stats, history) work while rekordbox is open
- **Write tools** (create playlist, add tracks, cleanup) require **rekordbox to be closed** — pyrekordbox blocks commits when rekordbox is running
- Access to your rekordbox database (automatic detection supported)

### Installation

```bash
# Install dependencies with uv
uv sync

# Run the server
uv run rekordbox-mcp
```

### Configuration

The server supports both automatic database detection and manual configuration:

```bash
# Auto-detect rekordbox database (recommended)
uv run rekordbox-mcp

# Specify custom database path
uv run rekordbox-mcp --database-path /path/to/rekordbox/Pioneer
```

### MCP Client Setup

Add to your Claude Desktop configuration:

```json
{
  "mcpServers": {
    "rekordbox-database": {
      "command": "uv",
      "args": ["run", "rekordbox-mcp"],
      "cwd": "/path/to/rekordbox-mcp"
    }
  }
}
```

## The DJ Toolkit (optional — `toolkit/` + `skills/`)

Beyond the raw MCP tools, this repo ships an **agent-oriented workflow layer**: audio
analysis pipelines and Claude Code skills that learn *your* conventions instead of
imposing generic ones. Nothing about it is preconfigured to any particular library — a
one-time onboarding maps everything to yours.

**The design principle: your data is ground truth.** Your MyTags outrank audio models;
your existing hot cues define your cue system; your star ratings define energy. Audio
analysis only fills gaps, and only ever *proposes*.

What it can do after onboarding:
- **Mine your hot-cue system** from the cues you've already placed (`mine_cue_system.py`)
  — detects your anchor slot (e.g. "C = the drop") and your per-genre ladder of offsets,
  with per-slot consistency stats. Validated: rediscovered a 1,400-track library's full
  ladder at 93-99% per-slot consistency.
- **Fill cue ladders automatically**: you set one anchor cue while auditioning; the
  toolkit derives the rest (~99% faithful, pure beat-grid arithmetic). Plus an optional
  ML drop-detector for bulk proposals (trained on *your* cues; always approval-gated).
- **Derive energy tags from star ratings**, sync rating→color schemes, and catch
  vocal tracks by credit sweep + audio suggestion.
- **Character calibration**: a melodic-vs-heavy audio model fitted against your own tags
  (with honestly-documented limits — see the field notes).

**Setup:** install the MCP (below), then run the **`dj-onboard`** skill from
`skills/dj-onboard/` — it connects, maps your tags, mines your cue system, and writes
`~/.dj-toolkit/config.json`. Copy the other skills (`cue-tracks`, `process-imports`,
`refresh-dj-engine`) into `~/.claude/skills/` to drive the workflows conversationally.
All toolkit scripts are configured entirely by that config file; generated artifacts stay
in the workspace directory, never in your library or this repo.

Hard-won knowledge about the rekordbox database itself (relinking, cue internals, ORM
traps, smart playlists) is written up in **[docs/FIELD_NOTES.md](docs/FIELD_NOTES.md)**.

## Available Tools (44 tools + 1 resource)

### Search & Discovery
- **`search_tracks`** - Advanced multi-field track search with filtering (genre, key, BPM, artist, title, rating, etc.)
- **`get_track_details`** - Get full metadata for a specific track by ID
- **`get_tracks_by_key`** - Find tracks in a specific musical key (e.g., "5A", "12B")
- **`get_tracks_by_bpm_range`** - Find tracks within a BPM range
- **`get_genre_filepaths`** - Get filepaths for tracks matching a genre (token-efficient, returns only paths)
- **`get_most_played_tracks`** - Get tracks ranked by play count
- **`get_top_rated_tracks`** - Get tracks ranked by rating
- **`get_unplayed_tracks`** - Get tracks with zero play count
- **`get_track_file_path`** - Get the file system path for a specific track
- **`search_tracks_by_filename`** - Search tracks by partial filename match

### Library Analytics
- **`get_library_stats`** - Comprehensive library statistics (track count, playtime, BPM, genres)
- **`analyze_library`** - Custom grouping and aggregation (by genre, key, year, artist, or rating)
- **`validate_track_ids`** - Verify a list of track IDs and report which are valid/invalid

### Playlist Operations
- **`get_playlists`** - List all playlists including smart playlists
- **`get_playlist_tracks`** - Get all tracks in a specific playlist
- **`create_playlist`** - Create new playlist or folder ⚠️ (Mutation)
- **`add_track_to_playlist`** - Add single track to playlist ⚠️ (Mutation)
- **`add_tracks_to_playlist`** - Add multiple tracks to playlist in one operation ⚠️ (Mutation)
- **`remove_track_from_playlist`** - Remove track from playlist ⚠️ (Mutation)
- **`delete_playlist`** - Delete playlist permanently ⚠️ (Destructive)

### Track Metadata
- **`get_available_colors`** - List valid color names/IDs defined in the database
- **`get_my_tags`** - List the MyTag tree (groups and assignable tags)
- **`get_track_my_tags`** - List MyTags currently assigned to a specific track
- **`set_track_rating`** - Set a track's star rating (0-5) ⚠️ (Mutation)
- **`set_track_color`** - Set or clear a track's color label, by color name ⚠️ (Mutation)
- **`set_track_comment`** - Set or clear a track's comment text ⚠️ (Mutation)
- **`add_track_my_tag`** - Assign an existing MyTag to a track ⚠️ (Mutation)
- **`remove_track_my_tag`** - Unassign a MyTag from a track ⚠️ (Mutation)

> ℹ️ MyTag *definitions* (the tags/groups themselves) must already exist in rekordbox — these tools only assign or unassign existing tags on tracks; they cannot create or delete tag definitions.

### Cue Points & Beat Grid
- **`get_track_cues`** - List a track's cue points with decoded slot letters ("A"-"H", "memory") and positions
- **`get_track_beatgrid`** - Read a track's beat grid: every beat, downbeats, and 8-bar phrase starts (for musically-placed cues)
- **`add_track_cue`** - Add a hot cue or memory cue at a position; snaps to the nearest beat by default (also "downbeat", "phrase", or "none"); refuses occupied slots unless `overwrite=True` ⚠️ (Mutation)
- **`update_track_cue`** - Move an existing cue to a new position (same snapping) ⚠️ (Mutation)
- **`delete_track_cue`** - Remove a cue from a slot (soft delete, exactly as rekordbox does) ⚠️ (Destructive)

> ℹ️ Cue writes keep both of rekordbox's internal representations in sync (the `djmdCue` rows *and* the `contentCue` JSON mirror), use the verified slot mapping (A=1…H=9, Kind 4 reserved, Kind 0 = memory), and never need to touch analysis files — cues live in the database only. See [docs/FIELD_NOTES.md](docs/FIELD_NOTES.md) for the full story.

### DJ History & Analytics
- **`get_history_sessions`** - Get all DJ history sessions with metadata
- **`get_session_tracks`** - Get all tracks played in a specific session
- **`get_recent_sessions`** - Get sessions within a specified number of days
- **`search_history_sessions`** - Search sessions by name, year, month, or minimum track count
- **`get_history_stats`** - Comprehensive DJ performance statistics and insights

### Track Import
- **`import_track`** - Import a single audio file into the library; reads ID3 tags via mutagen by default, accepts metadata overrides ⚠️ (Mutation)
- **`import_tracks`** - Batch-import files and/or directories (recursive, extension filter); returns track IDs for follow-up playlist actions ⚠️ (Mutation)

> ℹ️ Imported tracks are **unanalyzed** — waveforms, beatgrids, and hot cues are generated by rekordbox itself. After import, open rekordbox and run *Analyze Tracks* on the new imports. Supported formats: mp3, m4a, flac, wav, aiff.

### Library Cleanup
- **`find_broken_tracks`** - Scan for missing files, Apple Music streams, empty paths, and orphaned playlist refs
- **`cleanup_orphaned_playlist_entries`** - Remove stale playlist entries referencing deleted tracks ⚠️ (Mutation)
- **`remove_broken_tracks`** - Soft-delete tracks by ID and remove from all playlists ⚠️ (Destructive)

### Database Management
- **`connect_database`** - Explicitly connect with optional custom database path

### Resources
- **`database-status`** - Current connection status and basic stats

⚠️ **Mutation operations** modify your rekordbox database and create automatic backups  
⚠️ **Destructive operations** permanently delete data and require extra confirmation

## Examples

### Search for tracks by key and BPM
```python
# Find tracks in 5A key with BPM between 120-130
search_tracks(key="5A", bpm_min=120, bpm_max=130, limit=20)
```

### Access DJ History
```python
# Get recent DJ sessions
get_recent_sessions(days=30)

# Get tracks from a specific session
get_session_tracks(session_id="12345")
```


### Get library insights
```python
# Comprehensive library statistics
get_library_stats()

# DJ performance statistics
get_history_stats()
```

### Playlist Management
```python
# Create a new playlist
create_playlist(name="Hidden Bangers", parent_id="root")

# Add single track to playlist
add_track_to_playlist(playlist_id="136766232", track_id="218048716")

# Add multiple tracks efficiently (recommended for batch operations)
add_tracks_to_playlist(
    playlist_id="136766232", 
    track_ids=["218048716", "253968855", "148359536", "76341043"]
)

# Remove track from playlist
remove_track_from_playlist(playlist_id="136766232", track_id="218048716")

# Delete playlist (with safety confirmation)
delete_playlist(playlist_id="136766232")
```

### Importing New Tracks
```python
# Import a single file — auto-reads ID3 tags, allows overrides
import_track(
    path="/Users/me/Downloads/new_banger.mp3",
    rating=5,
    genre="Deep House",
)

# Batch-import a directory (recursive by default) and stage for analysis
result = import_tracks(
    paths=["/Users/me/Auditioned/March"],
    recursive=True,
    auto_tag=True,
)

# Park imports in a playlist so they're easy to find in rekordbox
create_playlist(name="Unanalyzed Imports")
add_tracks_to_playlist(
    playlist_id="<id from above>",
    track_ids=[t["track_id"] for t in result["imported"]],
)
# Then open rekordbox and run Analyze Tracks on that playlist.
```

## Safety Features

- **Automatic Backups**: All mutation operations create automatic database backups before changes
- **FastMCP Safety Annotations**: Proper safety hints for mutation and destructive operations
- **Smart Playlist Protection**: Prevents deletion of intelligent playlists
- **Connection Validation**: Validates database connections and access
- **Error Handling**: Comprehensive error handling with detailed logging and rollback
- **Input Validation**: Input validation for all database operations
- **Batch Operation Safety**: Detailed reporting on success/failure of batch operations

**⚠️ Important**: These safety features are supplementary protections. Always maintain your own backups and use this software at your own risk.

## Development

### Project Structure
```
rekordbox_mcp/
   __init__.py          # Package initialization
   server.py            # FastMCP server and tool definitions
   database.py          # Database connection and operations
   models.py            # Pydantic data models
```

### Running Tests
```bash
uv run pytest
```

### Code Quality
```bash
# Format code
uv run black rekordbox_mcp/

# Lint code
uv run ruff rekordbox_mcp/

# Type checking
uv run mypy rekordbox_mcp/
```

## License

MIT License

## Disclaimer

**⚠️ USE AT YOUR OWN RISK ⚠️**

- This project is **not affiliated** with AlphaTheta (Pioneer DJ) or the pyrekordbox project
- This software **directly accesses your rekordbox database**
- **No warranty or guarantee is provided**
- The developers are **not responsible** for any damage to your rekordbox library
- **You assume all risk** when using this software

**ALWAYS backup your rekordbox library before use. Test thoroughly with backup copies before using on your main library.**

By using this software, you acknowledge that you understand these risks and agree to use it at your own responsibility.