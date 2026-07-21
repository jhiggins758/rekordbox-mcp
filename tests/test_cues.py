"""Tests for cue point reading and editing."""

import json

import pytest

from rekordbox_mcp.database import RekordboxDatabase


class TestSlotMapping:
    """Hot cue slots map to DjmdCue.Kind with 4 deliberately skipped."""

    def test_letters_map_to_kinds(self):
        assert RekordboxDatabase._cue_slot_to_kind("A") == 1
        assert RekordboxDatabase._cue_slot_to_kind("B") == 2
        assert RekordboxDatabase._cue_slot_to_kind("C") == 3
        assert RekordboxDatabase._cue_slot_to_kind("D") == 5
        assert RekordboxDatabase._cue_slot_to_kind("H") == 9

    def test_kind_4_is_never_a_slot(self):
        assert 4 not in RekordboxDatabase.CUE_SLOT_KINDS.values()

    def test_memory_cue_is_kind_zero(self):
        assert RekordboxDatabase._cue_slot_to_kind("memory") == 0
        assert RekordboxDatabase._cue_slot_to_kind("MEMORY") == 0

    def test_slot_is_case_and_space_insensitive(self):
        assert RekordboxDatabase._cue_slot_to_kind(" d ") == 5

    def test_round_trips(self):
        for letter, kind in RekordboxDatabase.CUE_SLOT_KINDS.items():
            assert RekordboxDatabase._kind_to_cue_slot(kind) == letter
        assert RekordboxDatabase._kind_to_cue_slot(0) == "memory"

    def test_unknown_kind_is_labelled_not_crashed(self):
        assert RekordboxDatabase._kind_to_cue_slot(12) == "kind12"

    def test_unknown_slot_rejected(self):
        with pytest.raises(ValueError):
            RekordboxDatabase._cue_slot_to_kind("Z")


class TestFrameConversion:
    """InFrame = floor(InMsec * 150 / 1000) — exact on all 11,684 real rows."""

    @pytest.mark.parametrize(
        "msec,frame", [(0, 0), (46, 6), (21424, 3213), (44183, 6627), (88321, 13248)]
    )
    def test_known_values(self, msec, frame):
        assert RekordboxDatabase._msec_to_frame(msec) == frame

    def test_formats_position(self):
        assert RekordboxDatabase._format_position(88321) == "1:28.321"
        assert RekordboxDatabase._format_position(0) == "0:00.000"


class TestGetTrackCues:
    async def test_returns_cues_sorted_by_position(self, database):
        cues = await database.get_track_cues("1")
        assert [c["position_ms"] for c in cues] == [1000, 30000]

    async def test_decodes_slots(self, database):
        cues = await database.get_track_cues("1")
        assert cues[0]["slot"] == "memory"
        assert cues[0]["is_memory_cue"] is True
        assert cues[1]["slot"] == "A"
        assert cues[1]["is_hot_cue"] is True

    async def test_filters_soft_deleted(self, database):
        cues = await database.get_track_cues("1")
        assert "c3" not in [c["cue_id"] for c in cues]

    async def test_track_without_cues(self, database):
        assert await database.get_track_cues("2") == []

    async def test_unknown_track_rejected(self, database):
        with pytest.raises(RuntimeError):
            await database.get_track_cues("9999")


class TestAddTrackCue:
    async def test_adds_hot_cue(self, database, mock_db):
        result = await database.add_track_cue("2", 12000, "B", snap="none")
        assert result["slot"] == "B"
        assert result["kind"] == 2
        assert result["position_ms"] == 12000
        mock_db.commit.assert_called()

    async def test_sets_frame_from_position(self, database, mock_cues):
        await database.add_track_cue("2", 21424, "A", snap="none")
        added = [c for c in mock_cues if str(c.ContentID) == "2"][0]
        assert added.InFrame == 3213

    async def test_uses_rekordbox_defaults(self, database, mock_cues):
        await database.add_track_cue("2", 5000, "A", snap="none")
        added = [c for c in mock_cues if str(c.ContentID) == "2"][0]
        assert added.OutMsec == -1
        assert added.Color == -1
        assert added.ActiveLoop == 0
        assert added.ContentUUID == "uuid-content-2"

    async def test_occupied_slot_refused_by_default(self, database):
        with pytest.raises(RuntimeError, match="already used"):
            await database.add_track_cue("1", 5000, "A", snap="none")

    async def test_occupied_slot_replaced_with_overwrite(self, database, mock_cues):
        result = await database.add_track_cue(
            "1", 5000, "A", overwrite=True, snap="none"
        )
        assert result["replaced"]["position_ms"] == 30000
        old = [c for c in mock_cues if c.ID == "c2"][0]
        assert old.rb_local_deleted == 1

    async def test_memory_cue_slot_accepted(self, database, mock_cues):
        await database.add_track_cue("2", 500, "memory", snap="none")
        added = [c for c in mock_cues if str(c.ContentID) == "2"][0]
        assert added.Kind == 0

    async def test_negative_position_rejected(self, database):
        with pytest.raises(RuntimeError):
            await database.add_track_cue("2", -1, "A", snap="none")

    async def test_unknown_slot_rejected(self, database):
        with pytest.raises(RuntimeError):
            await database.add_track_cue("2", 1000, "Q", snap="none")

    async def test_unknown_track_rejected(self, database):
        with pytest.raises(RuntimeError):
            await database.add_track_cue("9999", 1000, "A", snap="none")


class TestUpdateTrackCue:
    async def test_moves_existing_cue(self, database, mock_cues):
        result = await database.update_track_cue("1", "A", 50000, snap="none")
        assert result["previous_position_ms"] == 30000
        assert result["position_ms"] == 50000
        moved = [c for c in mock_cues if c.ID == "c2"][0]
        assert moved.InMsec == 50000
        assert moved.InFrame == 7500

    async def test_missing_cue_rejected(self, database):
        with pytest.raises(RuntimeError, match="no cue in slot"):
            await database.update_track_cue("1", "H", 1000, snap="none")


class TestDeleteTrackCue:
    async def test_soft_deletes(self, database, mock_cues):
        result = await database.delete_track_cue("1", "A")
        assert result["deleted"] is True
        removed = [c for c in mock_cues if c.ID == "c2"][0]
        assert removed.rb_local_deleted == 1

    async def test_empty_slot_is_a_safe_noop(self, database):
        result = await database.delete_track_cue("1", "H")
        assert result["deleted"] is False


class TestContentCueBlob:
    """Every mutation rewrites contentCue.Cues to match the DjmdCue rows."""

    async def test_blob_matches_rows(self, database, mock_content_cues):
        await database.add_track_cue("1", 60000, "B", snap="none")
        blob = json.loads([r for r in mock_content_cues if r.ContentID == "1"][0].Cues)
        cues = await database.get_track_cues("1")
        assert len(blob) == len(cues) == 3
        assert sorted(e["ID"] for e in blob) == sorted(c["cue_id"] for c in cues)

    async def test_blob_is_compact_json(self, database, mock_content_cues):
        await database.add_track_cue("1", 60000, "B", snap="none")
        raw = [r for r in mock_content_cues if r.ContentID == "1"][0].Cues
        assert ", " not in raw and '": ' not in raw

    async def test_blob_timestamps_are_utc_iso(self, database, mock_content_cues):
        await database.add_track_cue("1", 60000, "B", snap="none")
        blob = json.loads([r for r in mock_content_cues if r.ContentID == "1"][0].Cues)
        assert all(e["created_at"].endswith("+00:00") for e in blob)
        assert all("T" in e["created_at"] for e in blob)

    async def test_blob_row_created_when_missing(self, database, mock_content_cues):
        await database.add_track_cue("2", 1000, "A", snap="none")
        row = [r for r in mock_content_cues if r.ContentID == "2"][0]
        assert row.ID == "uuid-content-2"
        assert len(json.loads(row.Cues)) == 1

    async def test_deleted_cue_leaves_blob(self, database, mock_content_cues):
        await database.delete_track_cue("1", "A")
        blob = json.loads([r for r in mock_content_cues if r.ContentID == "1"][0].Cues)
        assert [e["Kind"] for e in blob] == [0]


class TestBeatgrid:
    async def test_reads_grid(self, database):
        grid = await database.get_track_beatgrid("1")
        assert grid["has_beatgrid"] is True
        assert grid["beat_count"] == 64
        assert grid["first_beat_ms"] == 52
        assert grid["bpm"] == 124.0

    async def test_downbeats_are_every_fourth_beat(self, database):
        grid = await database.get_track_beatgrid("1")
        assert len(grid["downbeats_ms"]) == 16
        assert grid["downbeats_ms"][0] == 52

    async def test_phrases_are_every_eight_bars(self, database):
        grid = await database.get_track_beatgrid("1")
        assert len(grid["phrase_starts_ms"]) == 2

    async def test_unanalyzed_track_reports_no_grid(self, database):
        grid = await database.get_track_beatgrid("2")
        assert grid["has_beatgrid"] is False
        assert grid["downbeats_ms"] == []


class TestSnapping:
    async def test_snaps_to_nearest_beat(self, database, mock_cues):
        # Beat 2 sits at ~397ms; ask for 380ms and expect it to land there
        result = await database.add_track_cue("1", 380, "B", snap="beat")
        assert result["position_ms"] == 397
        assert result["snapped_by_ms"] == 17

    async def test_snaps_to_downbeat(self, database):
        result = await database.add_track_cue("1", 1300, "B", snap="downbeat")
        assert result["position_ms"] == 1431
        assert result["snap"] == "downbeat"

    async def test_snap_none_is_exact(self, database):
        result = await database.add_track_cue("1", 1234, "B", snap="none")
        assert result["position_ms"] == 1234
        assert result["snapped_by_ms"] == 0

    async def test_snap_moves_less_than_half_a_beat(self, database):
        # A beat at 174 BPM is ~345ms, so no snap should move more than ~172ms
        result = await database.add_track_cue("1", 5000, "B", snap="beat")
        assert abs(result["snapped_by_ms"]) < 173

    async def test_missing_grid_falls_back_with_warning(self, database):
        result = await database.add_track_cue("2", 1234, "A", snap="beat")
        assert result["position_ms"] == 1234
        assert "no beat grid" in result["snap_warning"]

    async def test_unknown_snap_mode_rejected(self, database):
        with pytest.raises(RuntimeError):
            await database.add_track_cue("2", 1000, "A", snap="sideways")

    async def test_update_snaps_too(self, database):
        result = await database.update_track_cue("1", "A", 380, snap="beat")
        assert result["position_ms"] == 397
