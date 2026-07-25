# Field Notes: the rekordbox database, learned the hard way

Everything below was established empirically against live rekordbox 6.x libraries while
building this project — including a few places where documentation (or pyrekordbox's own
docstrings) will actively mislead you. Recorded so nobody has to rediscover it.

## Golden rules

- **rekordbox must be fully CLOSED for any DB write.** pyrekordbox's `commit()` refuses
  while the app runs. When guarding with a process check, match the rekordbox app
  processes (`rekordbox`, `rekordboxAgent`) exactly — a substring match will also catch
  your own `rekordbox-mcp` server process and deadlock you.
- **Back up before every mutation.** This server does it automatically
  (`master_backup_YYYYMMDD_HHMMSS.db` beside the DB). Keep that behavior.
- **Soft deletes.** rekordbox marks rows deleted via `rb_local_deleted = 1` rather than
  removing them. Filter it in every query, and delete the same way.

## Relinking moved files

Rewriting `DjmdContent.FolderPath` does **not** relink a moved track. rekordbox identifies
files through `rb_file_id` plus internal state, and a path-only rewrite can make things
worse (observed: a library went from 1,685 missing tracks to 2,942 after a bulk FolderPath
rewrite; restored from backup). To fix missing files either **put the file back at the
path rekordbox expects**, or use rekordbox's own *File > Library > Relocate* flow.

## pyrekordbox connection gotcha: `path=` vs `db_dir=`

`Rekordbox6Database(path=..., db_dir=...)`: **`path` selects the database file**;
`db_dir` only locates the companion `masterPlaylists6.xml` / share folder. Passing a
custom location via `db_dir` alone silently connects you to the *default* library — this
bit us hard (a "scratch" rehearsal mutated the real library). Pass
`path=<dir>/master.db` for custom locations.

## Hot cues

- **Cues live in the database only.** Local ANLZ analysis files (`.DAT`/`.EXT`) carry
  `count=0` in their cue tags (PCOB/PCO2); rekordbox writes ANLZ cues at *export* time.
  So cue editing never needs to touch analysis files — fortunate, because pyrekordbox
  lists those tags as unsupported for writing.
- **Slot mapping** (`DjmdCue.Kind`): hot cues are **A=1, B=2, C=3, D=5, E=6, F=7, G=8,
  H=9** — **Kind 4 is reserved** and never appears; **Kind 0 is a memory cue**.
  pyrekordbox's docstring for this field ("Load=3, Loop=4") is wrong — it's copy-pasted
  from the XML POSITION_MARK format. Verified by round-trip: written Kinds 1/2/3/5
  displayed as A/B/C/D in the rekordbox UI.
- **Two representations to keep in sync**: one `djmdCue` row per cue AND a compact JSON
  mirror of all of a track's cues in `contentCue.Cues` (one row per track, whose `ID` is
  the track's UUID; timestamps there are UTC ISO while `djmdCue` stores local datetimes).
  Which one rekordbox treats as authoritative is undocumented — write both.
- `InFrame = floor(InMsec * 150 / 1000)` — exact on every row of an 11k-cue library.
- In practice DJs place cues **on the beat grid**: ~82% within 10ms of a beat measured.
  Snap-to-beat is the right default for programmatic cue placement.

## ORM traps (pyrekordbox 0.4.3)

- **Freshly created rows have `rb_local_deleted = None`** (not 0) until session flush.
  An "active rows" filter written as `== 0` silently drops rows you just created — filter
  on *falsy* instead.
- **`AnlzFile.__len__` / `__contains__` recurse infinitely** (`anlz/file.py`). Never use
  `in file`, `len(file)`, or `if not file:` on an AnlzFile — use `file.tag_types` and
  explicit `is None` checks.
- `DjmdContent.Title` is a plain string column; artist/genre/album/key are relationship
  rows. Helpers that unwrap `.Name` must not be applied to `Title` (it returns empty and
  you'll silently match against nothing).
- USN handling is automatic if you go through `db.add()` + `commit()` — the registry
  buffers changes and `autoincrement_local_update_count` stamps `rb_local_usn`.

## Smart playlists

Smart playlists store **zero** `DjmdSongPlaylist` rows — membership is computed from a
`SmartList` XML blob on the playlist row. Read the XML to understand them:
`<CONDITION PropertyName="myTag" Operator="8" ValueLeft="<tag-id>"/>` means "has MyTag".
This also means a user's "genre" playlists may really be **MyTag-driven** — the tag, not
the genre string, is their curated truth. Check before assuming.

## Misc conventions

- **BPM is stored ×100** (`17400` = 174.0).
- Playlist folders are `Attribute = 1`.
- MyTag assignments live in `DjmdSongMyTag` (create with fresh UUIDs and a `TrackNo` of
  existing-count+1).
- MyTag IDs are **per-database** — never hardcode them across libraries (this repo's
  toolkit maps them via config at onboarding).
- Audio-derived labels go stale: any flag snapshotted at extract time (e.g. "was this
  track tagged X when analyzed") must be refreshed from the live DB before being trusted.

## Honest limits of audio analysis (measured)

- **"Heaviness" scoring** (spectral brightness + sub-bass) does **not** reliably match
  what a DJ calls heavy — in an A/B against a user's own edits it was anti-correlated.
  Mid-bass growl (~200-800 Hz modulation), which likely drives the perception, isn't
  captured by these features. Treat audio character scores as soft hints only.
- **Demucs vocal separation** on bass-heavy electronic music bleeds synths into the vocal
  stem: ~26% of known-vocal tracks read as instrumental, and vocal-activity fraction
  doesn't separate the classes. Users' own vocal tags and artist credits ("feat.", named
  vocalists) are far more reliable signals.
- **Drop detection** peaks around 55-65% beat-perfect (learned ranker trained on ~1,000
  of the user's own anchor cues; top-3 ~90%). Good enough to propose, never to auto-apply.
  Deriving a cue ladder from a **user-placed** anchor, by contrast, is ~99% faithful —
  design workflows around the human placing one anchor.
