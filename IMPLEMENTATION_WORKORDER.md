# Work Order: Track Metadata Editing Tools (rating / color / comments / MyTags)

This document is a self-contained implementation guide. It assumes you are an agent
working in this repo (`~/rekordbox-mcp`, a fork of `davehenke/rekordbox-mcp`) with no
prior context. Follow it closely; deviations should be justified in your final report.

## Goal

Add MCP tools that edit metadata on **existing** tracks in the rekordbox database:

| Tool | Kind | What it does |
|---|---|---|
| `set_track_rating` | mutation | Set star rating (0–5) on a track |
| `set_track_color` | mutation | Set/clear the color label on a track, by color **name** |
| `set_track_comment` | mutation | Set/clear the comment text on a track |
| `add_track_my_tag` | mutation | Assign an existing MyTag to a track |
| `remove_track_my_tag` | mutation | Unassign a MyTag from a track |
| `get_available_colors` | read | List valid color names/IDs from `djmdColor` |
| `get_my_tags` | read | List the MyTag tree (groups + tags) from `djmdMyTag` |
| `get_track_my_tags` | read | List MyTags currently assigned to one track |

**Out of scope**: cue point writing (pyrekordbox mainline doesn't support it yet),
creating/deleting MyTag *definitions* (only assignment to tracks), key/BPM overrides.

## Architecture you must follow (verified facts, do not re-derive)

All of the following was confirmed by reading the actual sources — this repo's
`rekordbox_mcp/{database,models,server}.py` and the installed
`pyrekordbox` 0.4.4 (`.venv/lib/python3.13/site-packages/pyrekordbox/db6/`).

1. **Layering**: `server.py` defines `@mcp.tool()` functions (FastMCP 2.x) that call
   methods on a global `RekordboxDatabase` instance (`db`) defined in `database.py`,
   which wraps `pyrekordbox.Rekordbox6Database` (`self.db`). Pydantic models live in
   `models.py`. There is no other registration step — the decorator is the manifest.

2. **Mutation method template** (in `database.py`) — every new mutation method must
   follow this exact shape, copied from `add_track_to_playlist` (database.py ~line 1077):

   ```python
   async def my_mutation(self, ...) -> <ret>:
       if not self.db:
           raise RuntimeError("Database not connected")

       def _inner():
           self._create_backup()          # dedup'd, 5-min cooldown — always first
           # ... perform the write via self.db ...
           self.db.commit()
           self._invalidate_content_cache()
           logger.info(...)
           return <result>

       try:
           return await asyncio.to_thread(_inner)
       except Exception as e:
           logger.error(f"...: {e}")
           if self.db and hasattr(self.db, "rollback"):
               self.db.rollback()
           raise RuntimeError(f"...: {str(e)}")
   ```

3. **Read method template**: same but no backup/commit/invalidate, no rollback handler —
   see `get_track_by_id` (database.py ~line 252).

4. **MCP tool template** (in `server.py`) — mutations mirror `add_track_to_playlist`
   (server.py ~line 607): decorated with
   `@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": <see below>})`,
   docstring contains the line `⚠️ CAUTION: This modifies your rekordbox database!`,
   body starts `await ensure_database_connected()`, wraps the db call in
   `try/except` returning `{"status": "success"|"error", "message": ..., ...}` dicts —
   tools **catch** exceptions from the db layer and convert to error dicts; they do
   not let exceptions escape. Read tools use bare `@mcp.tool()` and may raise
   `ValueError` for not-found (matching `get_track_details`).

5. **IDs are strings everywhere**. In pyrekordbox 0.4.4 every PK/FK
   (`DjmdContent.ID`, `DjmdColor.ID`, `DjmdContent.ColorID`, `DjmdMyTag.ID`,
   `DjmdSongMyTag.{ID,MyTagID,ContentID}`) is `VARCHAR(255)`. The existing repo code
   passes `int(track_id)` to `get_content(ID=...)` and it works (SQLite coerces);
   keep tool parameters as `str` like every existing tool.

6. **pyrekordbox helpers that already exist** (on `self.db`, i.e.
   `Rekordbox6Database`) — use these, do not write raw SQL:
   - `get_content(ID=...)` → single `DjmdContent` or None
   - `get_color()` / `get_color(ID=...)` → query over `DjmdColor` (`ID`, `ColorCode`,
     `SortKey`, `Commnt` — `Commnt` is the color *name*, e.g. "Rose")
   - `get_my_tag()` / `get_my_tag(ID=...)` → query over `DjmdMyTag` (`ID`, `Seq`,
     `Name`, `Attribute`, `ParentID`)
   - `get_my_tag_songs(**filters)` → query over `DjmdSongMyTag` (`ID`, `MyTagID`,
     `ContentID`, `TrackNo`)
   - `add(instance)` → session add
   - `commit()` → **handles USN bookkeeping automatically** via
     `registry.autoincrement_local_update_count(set_row_usn=True)`; also refuses to
     commit if rekordbox is running (raises RuntimeError) — this is the safety gate.
   - Filtered `get_*` helpers return a Query when called with no/multi kwargs and a
     single row (or None) when called with a unique key like `ID=` — same
     `_parse_query_result` behavior as `get_content`. When iterating all rows, call
     e.g. `list(self.db.get_color())`.

7. **Row-insert pattern for `DjmdSongMyTag`** — mirror `add_to_playlist`
   (pyrekordbox `db6/database.py` line 786), which inserts the structurally-identical
   `DjmdSongPlaylist`. The pattern sets exactly these fields and nothing else
   (USN etc. are handled by `commit()`):

   ```python
   from uuid import uuid4
   import datetime as _dt

   from pyrekordbox.db6 import tables   # add this import to database.py

   now = _dt.datetime.now()
   row = tables.DjmdSongMyTag.create(
       ID=str(uuid4()),
       MyTagID=str(mytag_id),
       ContentID=str(track_id),
       TrackNo=<count of existing DjmdSongMyTag rows for this ContentID> + 1,
       UUID=str(uuid4()),
       created_at=now,
       updated_at=now,
   )
   self.db.add(row)
   ```

   Note `.create(...)` (not the bare constructor) — it's a classmethod on the table
   Base that constructs the row with change-tracking disabled, same as pyrekordbox
   uses internally.

8. **Rating scale**: `DjmdContent.Rating` in the live DB is plain 0–5. (The
   0/51/…/255 mapping exists only in pyrekordbox's XML interface, `rbxml.py` —
   irrelevant here.) Validate `0 <= rating <= 5`.

9. **Deleting a `DjmdSongMyTag` row**: use the session's delete. `RekordboxDatabase`
   exposes `self.db.session` (pyrekordbox keeps the SQLAlchemy session there), but
   prefer `self.db.delete(row)` if `Rekordbox6Database.delete` exists — **check
   first** with `grep -n "def delete" .venv/lib/python3.13/site-packages/pyrekordbox/db6/database.py`;
   if there's no public delete helper, use `self.db.session.delete(row)`. Whichever
   you use, note it in your report.

---

## Step-by-step implementation

Work in this order. The venv is at `.venv/` (Python 3.13, package installed
editable with dev extras). Run everything from the repo root `~/rekordbox-mcp`.

### Step 0 — Baseline sanity

1. `git checkout -b metadata-editing-tools` (work on a branch; do not commit to main).
2. Run the existing test suite to establish a green baseline:
   `.venv/bin/python -m pytest tests/ -q`
   Record any pre-existing failures — you are not responsible for fixing them, but
   you must not add new ones.
3. Read `tests/conftest.py` to learn how the existing tests fake/mock the database
   (they must not need a real rekordbox library). Match that approach for new tests.

### Step 1 — `models.py`: add the `MyTag` model

Add after the `Track` model:

```python
class MyTag(BaseModel):
    """A rekordbox MyTag (tag definition, possibly a group node in the tag tree)."""

    id: str = Field(..., description="Unique MyTag identifier")
    name: str = Field(..., description="Tag name")
    parent_id: Optional[str] = Field(
        None, description="Parent tag/group ID ('root' children have None)"
    )
    is_group: bool = Field(
        False, description="Whether this node is a tag group (has children) rather than an assignable tag"
    )
```

Notes:
- rekordbox MyTags are a two-level tree: group nodes (e.g. "Genre", "Components",
  "Situation") with tag children. In `djmdMyTag`, groups and tags share the table;
  `ParentID == "root"` (string literal) marks top-level group nodes. Determine
  `is_group` by whether the row's `ParentID` is `"root"` (groups sit at root; tags
  have a group's ID as ParentID). Verify this against real data during smoke testing
  and adjust if your library shows otherwise; also treat `Attribute` as a fallback
  signal if needed and note what you found.
- `parent_id`: normalize the literal string `"root"` to `None` (mirroring how
  `get_playlists` treats `ParentID != "root"` in database.py ~line 313).

### Step 2 — `database.py`: read methods

Add a new section `# --- Metadata operations ---` after the existing
`# --- Mutation operations ---` section. Import additions at top of file:
`from uuid import uuid4`, `from pyrekordbox.db6 import tables`, and add `MyTag` to
the `.models` import.

**2a. `get_available_colors`**

```python
async def get_available_colors(self) -> List[Dict[str, Any]]:
    """List all color labels defined in the database."""
    if not self.db:
        raise RuntimeError("Database not connected")

    def _inner():
        colors = list(self.db.get_color())
        colors.sort(key=lambda c: getattr(c, "SortKey", 0) or 0)
        return [
            {
                "id": str(c.ID),
                "name": c.Commnt or "",
                "color_code": getattr(c, "ColorCode", None),
            }
            for c in colors
        ]

    return await asyncio.to_thread(_inner)
```

**2b. `get_my_tags`**

Return every non-deleted row of `djmdMyTag` as a `MyTag`, sorted by
(`ParentID`, `Seq`). Filter `rb_local_deleted == 0` the same way `_get_active_content`
does (`getattr(row, "rb_local_deleted", 0) == 0`).

```python
async def get_my_tags(self) -> List[MyTag]: ...
```

Body: `rows = [t for t in list(self.db.get_my_tag()) if getattr(t, "rb_local_deleted", 0) == 0]`,
map to `MyTag(id=str(t.ID), name=t.Name or "", parent_id=None if (t.ParentID in (None, "root")) else str(t.ParentID), is_group=(t.ParentID in (None, "root")))`.

**2c. `get_track_my_tags`**

```python
async def get_track_my_tags(self, track_id: str) -> List[MyTag]: ...
```

Body: query `self.db.get_my_tag_songs(ContentID=str(track_id))` — when a filter
kwarg matches multiple rows this returns a Query; call `list(...)` on it. Filter
`rb_local_deleted == 0`. For each row, resolve the tag via
`self.db.get_my_tag(ID=row.MyTagID)`; skip rows whose tag no longer exists or is
deleted. Return `MyTag` objects (these are leaf tags, `is_group=False`).
If the track itself doesn't exist, return `[]` (consistent with a "no tags" answer;
the MCP tool layer will surface not-found separately if needed).

**2d. Color name resolution helper** (sync, private — used by reads and writes):

```python
def _resolve_color_by_name(self, color_name: str):
    """Case-insensitive lookup of a DjmdColor row by its name (Commnt). None if no match."""
    target = color_name.strip().lower()
    for c in list(self.db.get_color()):
        if (c.Commnt or "").strip().lower() == target:
            return c
    return None
```

**2e. Color on reads** — in `_content_to_track()` (database.py ~line 1318), populate
the existing-but-never-set `color` field. `DjmdContent` has a `Color` relationship
(`Color = relationship("DjmdColor", ...)`), so prefer:

```python
color_name = ""
color_obj = getattr(content, "Color", None)
if color_obj is not None:
    color_name = getattr(color_obj, "Commnt", "") or ""
```

and pass `color=color_name or None` into the `Track(...)` constructor. (Do NOT do a
per-track DB query here — `_content_to_track` runs in loops over the whole library;
the relationship attribute is lazy-loaded per accessed track, which is acceptable,
but an explicit query per track would double it.)

### Step 3 — `database.py`: mutation methods

All follow the mutation template from "Architecture" §2 exactly. All validate their
target rows first and raise `ValueError` with a clear message for bad input —
`ValueError` propagates out of `_inner`, gets caught by the generic handler, and is
re-raised as `RuntimeError`; the server tool layer converts it to an error dict.
(This matches how existing methods behave; do not invent a new error channel.)

**3a. `set_track_rating(track_id: str, rating: int) -> Dict[str, Any]`**

In `_inner`, before backup: none (backup is always literally first, per template).
After backup:
1. Validate `0 <= rating <= 5`, else `raise ValueError(f"Rating must be 0-5, got {rating}")`.
2. `content = self.db.get_content(ID=int(track_id))` — if falsy or
   `rb_local_deleted != 0`: `raise ValueError(f"Track {track_id} not found")`.
   (Cast to `int(...)` inside try — a non-numeric id should also land in the
   not-found error, mirroring `get_track_by_id`'s tolerance.)
3. `content.Rating = rating`
4. commit / invalidate / log; return
   `{"track_id": track_id, "rating": rating, "title": content.Title or ""}`.

**3b. `set_track_color(track_id: str, color_name: Optional[str]) -> Dict[str, Any]`**

1. Resolve content as in 3a.
2. If `color_name` is None or empty/whitespace: `content.ColorID = None` (clears the
   label), `resolved = None`.
3. Else: `color = self._resolve_color_by_name(color_name)`; if None,
   `raise ValueError(f"Unknown color '{color_name}'. Use get_available_colors to list valid names.")`;
   else `content.ColorID = str(color.ID)`, `resolved = color.Commnt`.
4. Commit etc.; return `{"track_id": ..., "color": resolved, "title": ...}`.

**3c. `set_track_comment(track_id: str, comment: str) -> Dict[str, Any]`**

1. Resolve content as in 3a.
2. `content.Commnt = comment` (empty string is a legal "clear").
3. Commit etc.; return `{"track_id": ..., "comment": comment, "title": ...}`.

**3d. `add_my_tag_to_track(track_id: str, mytag_id: str) -> Dict[str, Any]`**

1. Resolve content as in 3a (not-found → ValueError).
2. `tag = self.db.get_my_tag(ID=mytag_id)`; if falsy or deleted:
   `raise ValueError(f"MyTag {mytag_id} not found")`.
3. Reject group nodes: if `tag.ParentID in (None, "root")`:
   `raise ValueError(f"MyTag {mytag_id} ('{tag.Name}') is a tag group, not an assignable tag")`.
4. Idempotency guard: `existing = [r for r in list(self.db.get_my_tag_songs(ContentID=str(track_id), MyTagID=str(mytag_id))) if getattr(r, "rb_local_deleted", 0) == 0]`
   — if non-empty, **do not** insert; return
   `{"track_id": ..., "mytag_id": ..., "tag_name": tag.Name, "already_assigned": True}`.
   (Note: when both kwargs are passed, `get_my_tag_songs` may return a single row
   or a Query depending on `_parse_query_result` — handle both: wrap with a small
   normalizer that turns a row into `[row]` and a Query into `list(query)`. Check
   `_parse_query_result` in pyrekordbox `db6/database.py` to confirm which you get
   for two-kwarg filters, and write the normalizer accordingly.)
5. Insert per Architecture §7 (uuid4 ID + UUID, `TrackNo` = count of that content's
   existing active tag rows + 1, `created_at`/`updated_at` = now, `.create(...)` then
   `self.db.add(row)`).
6. Commit etc.; return `{"track_id": ..., "mytag_id": ..., "tag_name": tag.Name, "already_assigned": False}`.

**3e. `remove_my_tag_from_track(track_id: str, mytag_id: str) -> Dict[str, Any]`**

1. Find matching active rows (same normalized query as 3d step 4). Do **not**
   error if the track or tag doesn't exist — removal of a non-existent link is a
   no-op success: return `{"track_id": ..., "mytag_id": ..., "removed": False}`.
2. If rows found: delete them (Architecture §9 — check for a public
   `Rekordbox6Database.delete` first, fall back to `self.db.session.delete(row)`),
   commit etc., return `{"track_id": ..., "mytag_id": ..., "removed": True}`.

### Step 4 — `server.py`: MCP tools

Add a section comment `# Track Metadata Tools` after the playlist mutation tools.
Each mutation tool mirrors `add_track_to_playlist` exactly (annotations, caution
docstring, ensure-connected, try/except → status dict). Each read tool mirrors
`get_playlists` / `get_track_details`.

Signatures and annotation choices:

```python
@mcp.tool()                                   # read
async def get_available_colors() -> List[Dict[str, Any]]: ...

@mcp.tool()                                   # read
async def get_my_tags() -> List[Dict[str, Any]]: ...
    # returns [tag.model_dump() for tag in await db.get_my_tags()]

@mcp.tool()                                   # read
async def get_track_my_tags(track_id: str) -> List[Dict[str, Any]]: ...

@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": True})
async def set_track_rating(track_id: str, rating: int) -> Dict[str, Any]: ...

@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": True})
async def set_track_color(track_id: str, color_name: Optional[str] = None) -> Dict[str, Any]: ...
    # docstring must tell the model: pass color_name=None (or omit) to clear;
    # call get_available_colors first for valid names

@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": True})
async def set_track_comment(track_id: str, comment: str) -> Dict[str, Any]: ...

@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": True})
async def add_track_my_tag(track_id: str, mytag_id: str) -> Dict[str, Any]: ...
    # docstring: use get_my_tags to find tag IDs; groups are not assignable

@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": True})
async def remove_track_my_tag(track_id: str, mytag_id: str) -> Dict[str, Any]: ...
```

All six mutations are genuinely idempotent (set-to-value; guarded add; no-op remove),
hence `idempotentHint: True` on all. None are destructive in the delete-a-playlist
sense (`destructiveHint: False`) — worst case is overwriting one metadata field,
and a comment overwrite is recoverable from the auto-backup.

Success dict shape (match existing tools):

```python
return {
    "status": "success",
    "message": f"Set rating {rating} on track {track_id}",
    **result,        # the dict returned by the database method
}
```

Error handling in each mutation tool:

```python
except Exception as e:
    return {"status": "error", "message": f"Failed to set rating: {str(e)}"}
```

### Step 5 — Tests

Follow whatever mock/fixture pattern `tests/conftest.py` establishes (Step 0.3).
Add `tests/test_metadata.py` covering, at minimum:

- `set_track_rating`: happy path; rating 6 and -1 rejected; unknown track id rejected.
- `set_track_color`: resolves name case-insensitively; unknown name rejected;
  `None` clears `ColorID`.
- `set_track_comment`: sets text; empty string allowed.
- `add_my_tag_to_track`: inserts row with all 7 fields set (ID, MyTagID, ContentID,
  TrackNo, UUID, created_at, updated_at); second identical call is a no-op
  (`already_assigned: True`, row count unchanged); group node rejected; unknown
  tag/track rejected.
- `remove_my_tag_from_track`: removes existing row; second call no-op
  (`removed: False`); never raises for unknown ids.
- `_content_to_track`: populates `color` name when content has a Color relation.

Run: `.venv/bin/python -m pytest tests/ -q` — full suite, not just the new file.
No new failures vs. the Step 0 baseline.

### Step 6 — README

Update the README's tool table/list (it enumerates tools by category): add the
8 new tools under a "Track Metadata" heading, with the same caution language the
playlist mutation section uses. Mention that MyTag *definitions* must already exist
(created in rekordbox); these tools only assign/unassign them.

### Step 7 — Verification against a real database (requires the user)

Everything up to here runs against mocks. The live verification below **must not
run unattended** — it needs the user present, rekordbox closed, and their consent
at each stage. Present this checklist to the user rather than executing it yourself:

1. Close rekordbox. Make a manual full copy of
   `~/Library/Pioneer/rekordbox/` (macOS) to a safe location.
2. **Scratch rehearsal**: copy `master.db` + companions to a scratch dir; connect
   `RekordboxDatabase` at the scratch dir (`connect_database` tool takes a path);
   run: `get_available_colors`, `get_my_tags`, pick one real track →
   `set_track_rating`, `set_track_color`, `set_track_comment`, `add_track_my_tag`
   ×2 (second must no-op), `remove_track_my_tag` ×2 (second must no-op), invalid
   ids for each (must return clean error dicts). Confirm via `get_track_details` /
   `get_track_my_tags`.
3. Confirm the auto-created `master_backup_*.db` file exists **and** can be loaded
   (`Rekordbox6Database` pointed at a dir containing it, renamed to `master.db`).
4. Only after 2–3 pass: run one small pass against the real library on a
   throwaway track, reopen rekordbox, and visually verify rating/color/comment/tag
   in the UI (My Tag panel + color/rating columns), and that the library is otherwise
   intact.

## Known risks / watch-outs

- `_parse_query_result` behavior with multi-kwarg filters (single row vs Query) —
  verify empirically, normalize (Step 3d note). Getting this wrong breaks the
  idempotency guard silently.
- The `"root"` ParentID convention for MyTag groups is inferred from the playlist
  code's identical convention and community documentation; verify against real data
  in Step 7.2 before trusting `is_group`.
- `content.ColorID = None` to clear: confirm during rehearsal that rekordbox shows
  "no color" afterward rather than misbehaving; if rekordbox expects `""` instead of
  NULL, adjust (note which in your report).
- Do not touch `usn`, `rb_local_usn`, or `rb_data_status` anywhere — `commit()`
  owns them.
- Never call `commit()` outside `_inner` bodies that started with `_create_backup()`.
- pyrekordbox's `commit()` itself raises if rekordbox is running — surface that
  message untouched; it's the most user-actionable error in the system.
