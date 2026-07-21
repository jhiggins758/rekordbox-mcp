"""Shared test fixtures for rekordbox-mcp tests."""

from dataclasses import dataclass, field
from typing import Optional, List
from unittest.mock import MagicMock

import pytest

from rekordbox_mcp.database import RekordboxDatabase


# --- Mock dataclasses mimicking pyrekordbox ORM objects ---


@dataclass
class MockContent:
    ID: int
    Title: str = ""
    ArtistName: str = ""
    AlbumName: str = ""
    GenreName: str = ""
    KeyName: str = ""
    BPM: int = 0  # stored as int * 100
    Rating: int = 0
    DJPlayCount: int = 0
    Length: int = 0  # seconds
    FolderPath: str = ""
    Location: str = ""
    DateCreated: str = ""
    StockDate: str = ""
    BitRate: int = 0
    SampleRate: int = 0
    Commnt: str = ""
    rb_local_deleted: int = 0
    ReleaseYear: Optional[int] = None
    ColorID: Optional[str] = None
    Color: Optional[object] = None  # simulates the lazy-loaded Color relationship
    UUID: str = ""
    AnalysisDataPath: str = ""


@dataclass
class MockPlaylist:
    ID: int
    Name: str = ""
    ParentID: Optional[int] = None
    Attribute: int = 0  # 1 = folder
    is_smart_playlist: bool = False
    is_folder: bool = False
    SmartList: Optional[str] = None
    created_at: str = ""
    updated_at: str = ""
    rb_local_deleted: int = 0


@dataclass
class MockPlaylistSong:
    ID: int = 0
    PlaylistID: int = 0
    ContentID: int = 0
    TrackNo: int = 0
    rb_local_deleted: int = 0


@dataclass
class MockHistory:
    ID: int
    Name: str = ""
    ParentID: Optional[int] = None
    Attribute: int = 0  # 1 = folder
    DateCreated: str = ""
    rb_local_deleted: int = 0


@dataclass
class MockHistorySong:
    HistoryID: int = 0
    ContentID: int = 0
    TrackNo: int = 0
    rb_local_deleted: int = 0


@dataclass
class MockColor:
    ID: str
    ColorCode: int = 0
    SortKey: int = 0
    Commnt: str = ""
    rb_local_deleted: int = 0


@dataclass
class MockMyTag:
    ID: str
    Name: str = ""
    Seq: int = 0
    Attribute: int = 0
    ParentID: Optional[str] = None
    rb_local_deleted: int = 0


@dataclass
class MockSongMyTag:
    ID: str
    MyTagID: str
    ContentID: str
    TrackNo: int = 1
    UUID: str = ""
    created_at: str = ""
    updated_at: str = ""
    rb_local_deleted: int = 0


@dataclass
class MockCue:
    """Mimics a DjmdCue row. Kind 0 = memory cue, 1-9 = hot cue slots A-H."""

    ID: str
    ContentID: str
    InMsec: int = 0
    InFrame: int = 0
    InMpegFrame: int = 0
    InMpegAbs: int = 0
    OutMsec: int = -1
    OutFrame: int = 0
    OutMpegFrame: int = 0
    OutMpegAbs: int = 0
    Kind: int = 0
    Color: int = -1
    ColorTableIndex: int = 0
    ActiveLoop: int = 0
    Comment: str = ""
    BeatLoopSize: int = 0
    CueMicrosec: int = 0
    ContentUUID: str = ""
    UUID: str = ""
    created_at: Optional[object] = None
    updated_at: Optional[object] = None
    rb_local_deleted: int = 0


@dataclass
class MockContentCue:
    """Mimics a contentCue row — the JSON blob mirror of a track's cues."""

    ID: str
    ContentID: str
    Cues: str = "[]"
    rb_cue_count: Optional[int] = None
    UUID: str = ""
    rb_local_deleted: int = 0


class MockAnlzTag:
    """Stands in for a PQTZ beat-grid tag."""

    def __init__(self, beats, times_seconds):
        self._beats = beats
        self._times = times_seconds

    def get_beats(self):
        return self._beats

    def get_times(self):
        return self._times


class MockAnlzFile:
    """Stands in for an AnlzFile. Deliberately does NOT implement __len__ or
    __contains__ — production code must use tag_types and `is None`, because
    pyrekordbox 0.4.3's own __len__ recurses infinitely."""

    def __init__(self, tags):
        self._tags = tags

    @property
    def tag_types(self):
        return list(self._tags)

    def get_tag(self, key):
        return self._tags[key]


class QueryStub:
    """Minimal stand-in for a SQLAlchemy Query supporting the calls we make."""

    def __init__(self, rows):
        self._rows = rows

    def filter_by(self, **kwargs):
        rows = self._rows
        for key, value in kwargs.items():
            rows = [r for r in rows if str(getattr(r, key, None)) == str(value)]
        return QueryStub(rows)

    def all(self):
        return list(self._rows)

    def first(self):
        return self._rows[0] if self._rows else None

    def count(self):
        return len(self._rows)


# --- Fixtures ---


@pytest.fixture
def mock_content_list():
    """10 varied tracks for testing, plus 1 soft-deleted."""
    return [
        MockContent(
            ID=1,
            Title="Deep House Groove",
            ArtistName="DJ Alpha",
            GenreName="Deep House",
            KeyName="5A",
            BPM=12400,
            Rating=5,
            DJPlayCount=42,
            Length=360,
            FolderPath="/music/deep_house_groove.mp3",
            Location="/music/deep_house_groove.mp3",
            DateCreated="2024-01-15",
            BitRate=320,
            SampleRate=44100,
        ),
        MockContent(
            ID=2,
            Title="Techno Blast",
            ArtistName="DJ Beta",
            GenreName="Techno",
            KeyName="8B",
            BPM=13800,
            Rating=4,
            DJPlayCount=30,
            Length=420,
            FolderPath="/music/techno_blast.mp3",
            Location="/music/techno_blast.mp3",
            DateCreated="2024-02-20",
            BitRate=320,
            SampleRate=44100,
        ),
        MockContent(
            ID=3,
            Title="Trance Dream",
            ArtistName="DJ Gamma",
            GenreName="Trance",
            KeyName="12A",
            BPM=14000,
            Rating=3,
            DJPlayCount=10,
            Length=480,
            FolderPath="/music/trance_dream.mp3",
            Location="/music/trance_dream.mp3",
            DateCreated="2024-03-10",
            BitRate=256,
            SampleRate=44100,
        ),
        MockContent(
            ID=4,
            Title="Minimal Vibes",
            ArtistName="DJ Alpha",
            GenreName="Minimal",
            KeyName="2B",
            BPM=12800,
            Rating=4,
            DJPlayCount=25,
            Length=300,
            FolderPath="/music/minimal_vibes.mp3",
            Location="/music/minimal_vibes.mp3",
            DateCreated="2024-04-05",
            BitRate=320,
            SampleRate=48000,
        ),
        MockContent(
            ID=5,
            Title="Progressive Journey",
            ArtistName="DJ Delta",
            GenreName="Progressive House",
            KeyName="5A",
            BPM=12600,
            Rating=5,
            DJPlayCount=50,
            Length=540,
            FolderPath="/music/progressive_journey.mp3",
            Location="/music/progressive_journey.mp3",
            DateCreated="2024-05-12",
            BitRate=320,
            SampleRate=44100,
        ),
        MockContent(
            ID=6,
            Title="Drum and Bass Fury",
            ArtistName="DJ Epsilon",
            GenreName="Drum and Bass",
            KeyName="7A",
            BPM=17400,
            Rating=2,
            DJPlayCount=5,
            Length=270,
            FolderPath="/music/dnb_fury.mp3",
            Location="/music/dnb_fury.mp3",
            DateCreated="2024-06-01",
            BitRate=192,
            SampleRate=44100,
        ),
        MockContent(
            ID=7,
            Title="Ambient Chill",
            ArtistName="DJ Zeta",
            GenreName="Ambient",
            KeyName="1A",
            BPM=9000,
            Rating=3,
            DJPlayCount=0,
            Length=600,
            FolderPath="/music/ambient_chill.mp3",
            Location="/music/ambient_chill.mp3",
            DateCreated="2024-07-20",
            BitRate=320,
            SampleRate=48000,
        ),
        MockContent(
            ID=8,
            Title="House Party",
            ArtistName="DJ Alpha",
            GenreName="House",
            KeyName="10B",
            BPM=12800,
            Rating=0,
            DJPlayCount=0,
            Length=330,
            FolderPath="/music/house_party.mp3",
            Location="/music/house_party.mp3",
            DateCreated="2024-08-15",
            BitRate=256,
            SampleRate=44100,
        ),
        MockContent(
            ID=9,
            Title="Acid Techno Ride",
            ArtistName="DJ Beta",
            GenreName="Techno",
            KeyName="3A",
            BPM=14200,
            Rating=4,
            DJPlayCount=18,
            Length=390,
            FolderPath="/music/acid_techno.mp3",
            Location="/music/acid_techno.mp3",
            DateCreated="2024-09-01",
            BitRate=320,
            SampleRate=44100,
        ),
        MockContent(
            ID=10,
            Title="Deep Dub",
            ArtistName="DJ Gamma",
            GenreName="Dub Techno",
            KeyName="6B",
            BPM=12000,
            Rating=3,
            DJPlayCount=8,
            Length=450,
            FolderPath="/music/deep_dub.mp3",
            Location="/music/deep_dub.mp3",
            DateCreated="2024-10-10",
            BitRate=320,
            SampleRate=44100,
        ),
        # Apple Music streaming track (can't export to USB)
        MockContent(
            ID=11,
            Title="Streaming Track",
            ArtistName="DJ Stream",
            GenreName="House",
            KeyName="3A",
            BPM=12600,
            Rating=0,
            DJPlayCount=0,
            Length=200,
            FolderPath="apple-music:tracks:1234567890",
            Location="apple-music:tracks:1234567890",
            DateCreated="2024-11-01",
            BitRate=0,
            SampleRate=44100,
        ),
        # Soft-deleted track — should be filtered out
        MockContent(
            ID=99,
            Title="Deleted Track",
            ArtistName="Nobody",
            GenreName="Unknown",
            KeyName="1A",
            BPM=12000,
            Rating=0,
            DJPlayCount=0,
            Length=100,
            FolderPath="/music/deleted.mp3",
            Location="/music/deleted.mp3",
            rb_local_deleted=1,
        ),
    ]


@pytest.fixture
def mock_playlists():
    return [
        MockPlaylist(ID=100, Name="Warm Up", Attribute=0, created_at="2024-01-01"),
        MockPlaylist(ID=101, Name="Peak Time", Attribute=0, created_at="2024-02-01"),
        MockPlaylist(ID=102, Name="Sets", Attribute=1, is_folder=True),  # folder
        MockPlaylist(
            ID=103,
            Name="Smart Mix",
            Attribute=0,
            is_smart_playlist=True,
            SmartList="<criteria/>",
        ),
        MockPlaylist(ID=199, Name="Deleted Playlist", Attribute=0, rb_local_deleted=1),
    ]


@pytest.fixture
def mock_playlist_songs():
    return [
        MockPlaylistSong(ID=1001, PlaylistID=100, ContentID=1, TrackNo=1),
        MockPlaylistSong(ID=1002, PlaylistID=100, ContentID=5, TrackNo=2),
        MockPlaylistSong(ID=1003, PlaylistID=100, ContentID=3, TrackNo=3),
        MockPlaylistSong(
            ID=1004, PlaylistID=100, ContentID=99, TrackNo=4
        ),  # orphan: points to deleted content
        MockPlaylistSong(ID=1005, PlaylistID=101, ContentID=2, TrackNo=1),
        MockPlaylistSong(ID=1006, PlaylistID=101, ContentID=9, TrackNo=2),
    ]


@pytest.fixture
def mock_histories():
    return [
        MockHistory(
            ID=200, Name="2024", Attribute=1, DateCreated="2024-01-01"
        ),  # folder
        MockHistory(
            ID=201,
            Name="2024-08-15 Set",
            Attribute=0,
            DateCreated="2024-08-15 22:00:00",
        ),
        MockHistory(
            ID=202,
            Name="2024-09-01 Set",
            Attribute=0,
            DateCreated="2024-09-01 21:00:00",
        ),
    ]


@pytest.fixture
def mock_history_songs():
    return [
        MockHistorySong(HistoryID=201, ContentID=1, TrackNo=1),
        MockHistorySong(HistoryID=201, ContentID=2, TrackNo=2),
        MockHistorySong(HistoryID=201, ContentID=5, TrackNo=3),
        MockHistorySong(HistoryID=202, ContentID=4, TrackNo=1),
        MockHistorySong(HistoryID=202, ContentID=9, TrackNo=2),
    ]


@pytest.fixture
def mock_colors():
    return [
        MockColor(ID="1", ColorCode=16711680, SortKey=1, Commnt="Red"),
        MockColor(ID="2", ColorCode=16744192, SortKey=2, Commnt="Rose"),
        MockColor(ID="3", ColorCode=255, SortKey=3, Commnt="Blue"),
    ]


@pytest.fixture
def mock_my_tags():
    return [
        # Groups (top-level, ParentID == "root")
        MockMyTag(ID="g1", Name="Genre", Seq=1, ParentID="root"),
        MockMyTag(ID="g2", Name="Situation", Seq=2, ParentID="root"),
        # Assignable tags under the "Genre" group
        MockMyTag(ID="t1", Name="House", Seq=1, ParentID="g1"),
        MockMyTag(ID="t2", Name="Techno", Seq=2, ParentID="g1"),
        # Soft-deleted tag — should be filtered out
        MockMyTag(ID="t9", Name="Old Tag", Seq=3, ParentID="g1", rb_local_deleted=1),
    ]


@pytest.fixture
def mock_song_my_tags():
    """Track ID '1' already has MyTag 't1' assigned."""
    return [
        MockSongMyTag(
            ID="st1", MyTagID="t1", ContentID="1", TrackNo=1, UUID="uuid-st1"
        ),
    ]


@pytest.fixture
def mock_cues():
    """Track 1 has a memory cue and hot cue A; track 99 (deleted) has a stale cue."""
    return [
        MockCue(
            ID="c1",
            ContentID="1",
            InMsec=1000,
            InFrame=150,
            Kind=0,
            ContentUUID="uuid-content-1",
            UUID="uuid-c1",
        ),
        MockCue(
            ID="c2",
            ContentID="1",
            InMsec=30000,
            InFrame=4500,
            Kind=1,
            ContentUUID="uuid-content-1",
            UUID="uuid-c2",
        ),
        # Soft-deleted cue — must be filtered out everywhere
        MockCue(
            ID="c3",
            ContentID="1",
            InMsec=45000,
            InFrame=6750,
            Kind=2,
            ContentUUID="uuid-content-1",
            UUID="uuid-c3",
            rb_local_deleted=1,
        ),
    ]


@pytest.fixture
def mock_content_cues():
    return [MockContentCue(ID="uuid-content-1", ContentID="1", Cues="[]")]


@pytest.fixture
def mock_beatgrid():
    """A 174 BPM grid for track 1: 4 bars of beats starting at 52ms.

    At 174 BPM a beat is ~344.8ms. Beat numbers cycle 1-4 so every 4th entry
    is a downbeat.
    """
    beat_ms = 60000.0 / 174.0
    beats = [(i % 4) + 1 for i in range(64)]
    times = [(52 + i * beat_ms) / 1000.0 for i in range(64)]
    return MockAnlzFile({"PQTZ": MockAnlzTag(beats, times)})


@pytest.fixture
def mock_db(
    mock_content_list,
    mock_playlists,
    mock_playlist_songs,
    mock_histories,
    mock_history_songs,
    mock_colors,
    mock_my_tags,
    mock_song_my_tags,
    mock_cues,
    mock_content_cues,
    mock_beatgrid,
):
    """A MagicMock of Rekordbox6Database wired with test data."""
    db = MagicMock()

    for content in mock_content_list:
        if not content.UUID:
            content.UUID = f"uuid-content-{content.ID}"

    # get_content() with no args returns iterable of all content
    # get_content(ID=x) returns single item or None
    def get_content_side_effect(**kwargs):
        if "ID" in kwargs:
            content_id = kwargs["ID"]
            for c in mock_content_list:
                if c.ID == content_id:
                    return c
            return None
        return mock_content_list

    db.get_content = MagicMock(side_effect=get_content_side_effect)

    db.get_playlist = MagicMock(return_value=mock_playlists)

    def get_playlist_songs_side_effect(**kwargs):
        pid = kwargs.get("PlaylistID")
        return [s for s in mock_playlist_songs if s.PlaylistID == pid]

    db.get_playlist_songs = MagicMock(side_effect=get_playlist_songs_side_effect)

    db.get_history = MagicMock(return_value=mock_histories)

    def get_history_songs_side_effect(**kwargs):
        hid = kwargs.get("HistoryID")
        return [s for s in mock_history_songs if s.HistoryID == hid]

    db.get_history_songs = MagicMock(side_effect=get_history_songs_side_effect)

    db.add_to_playlist = MagicMock()
    db.remove_from_playlist = MagicMock()
    db.create_playlist = MagicMock(
        return_value=MockPlaylist(ID=500, Name="New Playlist")
    )
    db.create_playlist_folder = MagicMock(
        return_value=MockPlaylist(ID=501, Name="New Folder")
    )
    db.delete_playlist = MagicMock()
    db.commit = MagicMock()
    db.close = MagicMock()

    # --- Color / MyTag mocks ---

    def get_color_side_effect(**kwargs):
        if "ID" in kwargs:
            for c in mock_colors:
                if c.ID == kwargs["ID"]:
                    return c
            return None
        return mock_colors

    db.get_color = MagicMock(side_effect=get_color_side_effect)

    def get_my_tag_side_effect(**kwargs):
        if "ID" in kwargs:
            for t in mock_my_tags:
                if t.ID == kwargs["ID"]:
                    return t
            return None
        return mock_my_tags

    db.get_my_tag = MagicMock(side_effect=get_my_tag_side_effect)

    def get_my_tag_songs_side_effect(**kwargs):
        # Mirrors pyrekordbox's _parse_query_result: only "ID"/"registry_id"
        # kwargs collapse to a single row; ContentID/MyTagID filters always
        # return a query-like collection (here, a plain list).
        results = mock_song_my_tags
        if "ContentID" in kwargs:
            results = [r for r in results if r.ContentID == kwargs["ContentID"]]
        if "MyTagID" in kwargs:
            results = [r for r in results if r.MyTagID == kwargs["MyTagID"]]
        return results

    db.get_my_tag_songs = MagicMock(side_effect=get_my_tag_songs_side_effect)

    # --- Cue mocks ---

    def query_side_effect(table):
        name = getattr(table, "__name__", str(table))
        if name == "DjmdCue":
            return QueryStub(mock_cues)
        if name == "ContentCue":
            return QueryStub(mock_content_cues)
        return QueryStub([])

    db.query = MagicMock(side_effect=query_side_effect)

    # Deterministic so tests can assert on generated IDs
    db.generate_unused_id = MagicMock(return_value=555000111)
    db.flush = MagicMock()

    def read_anlz_file_side_effect(content, type_="DAT"):
        # Only track 1 is "analyzed" — everything else has no beat grid
        if getattr(content, "ID", None) == 1 and type_ == "DAT":
            return mock_beatgrid
        return None

    db.read_anlz_file = MagicMock(side_effect=read_anlz_file_side_effect)

    def add_side_effect(row):
        name = row.__class__.__name__
        if isinstance(row, MockSongMyTag) or name == "DjmdSongMyTag":
            mock_song_my_tags.append(row)
        elif isinstance(row, MockCue) or name == "DjmdCue":
            mock_cues.append(row)
        elif isinstance(row, MockContentCue) or name == "ContentCue":
            mock_content_cues.append(row)

    db.add = MagicMock(side_effect=add_side_effect)

    def delete_side_effect(row):
        if row in mock_song_my_tags:
            mock_song_my_tags.remove(row)

    db.delete = MagicMock(side_effect=delete_side_effect)

    return db


@pytest.fixture
def database(mock_db, tmp_path):
    """A RekordboxDatabase instance wired with mock db, ready to use."""
    rdb = RekordboxDatabase()
    rdb.db = mock_db
    rdb._connected = True
    rdb.database_path = tmp_path
    return rdb
