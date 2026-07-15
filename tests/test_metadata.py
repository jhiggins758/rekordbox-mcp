"""Tests for track metadata editing (rating, color, comment, MyTags)."""

import pytest

from tests.conftest import MockColor, MockContent


class TestSetTrackRating:
    async def test_happy_path(self, database, mock_db):
        result = await database.set_track_rating("1", 4)
        assert result["rating"] == 4
        assert result["track_id"] == "1"
        assert result["title"] == "Deep House Groove"
        mock_db.commit.assert_called()

    async def test_rating_too_high_rejected(self, database):
        with pytest.raises(RuntimeError):
            await database.set_track_rating("1", 6)

    async def test_rating_too_low_rejected(self, database):
        with pytest.raises(RuntimeError):
            await database.set_track_rating("1", -1)

    async def test_unknown_track_rejected(self, database):
        with pytest.raises(RuntimeError):
            await database.set_track_rating("9999", 3)


class TestSetTrackColor:
    async def test_resolves_name_case_insensitively(self, database, mock_content_list):
        result = await database.set_track_color("1", "rOsE")
        assert result["color"] == "Rose"
        content_1 = next(c for c in mock_content_list if c.ID == 1)
        assert content_1.ColorID == "2"

    async def test_unknown_color_rejected(self, database):
        with pytest.raises(RuntimeError):
            await database.set_track_color("1", "Not A Real Color")

    async def test_none_clears_color(self, database, mock_content_list):
        content_1 = next(c for c in mock_content_list if c.ID == 1)
        content_1.ColorID = "2"
        result = await database.set_track_color("1", None)
        assert result["color"] is None
        assert content_1.ColorID is None

    async def test_empty_string_clears_color(self, database, mock_content_list):
        content_1 = next(c for c in mock_content_list if c.ID == 1)
        content_1.ColorID = "2"
        result = await database.set_track_color("1", "   ")
        assert result["color"] is None
        assert content_1.ColorID is None


class TestSetTrackComment:
    async def test_sets_text(self, database, mock_content_list):
        result = await database.set_track_comment("1", "Great opener")
        assert result["comment"] == "Great opener"
        content_1 = next(c for c in mock_content_list if c.ID == 1)
        assert content_1.Commnt == "Great opener"

    async def test_empty_string_allowed(self, database, mock_content_list):
        result = await database.set_track_comment("1", "")
        assert result["comment"] == ""
        content_1 = next(c for c in mock_content_list if c.ID == 1)
        assert content_1.Commnt == ""

    async def test_unknown_track_rejected(self, database):
        with pytest.raises(RuntimeError):
            await database.set_track_comment("9999", "hello")


class TestAddMyTagToTrack:
    async def test_inserts_row_with_all_fields(self, database, mock_db, mock_song_my_tags):
        before_count = len(mock_song_my_tags)
        result = await database.add_my_tag_to_track("2", "t2")

        assert result["already_assigned"] is False
        assert result["tag_name"] == "Techno"
        assert len(mock_song_my_tags) == before_count + 1

        new_row = mock_song_my_tags[-1]
        assert new_row.ID
        assert new_row.MyTagID == "t2"
        assert new_row.ContentID == "2"
        assert new_row.TrackNo == 1
        assert new_row.UUID
        assert new_row.created_at is not None
        assert new_row.updated_at is not None
        mock_db.commit.assert_called()

    async def test_second_identical_call_is_noop(self, database, mock_song_my_tags):
        row_count_before = len(mock_song_my_tags)
        result = await database.add_my_tag_to_track("1", "t1")

        assert result["already_assigned"] is True
        assert len(mock_song_my_tags) == row_count_before

    async def test_group_node_rejected(self, database):
        with pytest.raises(RuntimeError):
            await database.add_my_tag_to_track("1", "g1")

    async def test_unknown_tag_rejected(self, database):
        with pytest.raises(RuntimeError):
            await database.add_my_tag_to_track("1", "nonexistent")

    async def test_unknown_track_rejected(self, database):
        with pytest.raises(RuntimeError):
            await database.add_my_tag_to_track("9999", "t1")


class TestRemoveMyTagFromTrack:
    async def test_removes_existing_row(self, database, mock_song_my_tags):
        result = await database.remove_my_tag_from_track("1", "t1")
        assert result["removed"] is True
        assert all(r.ContentID != "1" or r.MyTagID != "t1" for r in mock_song_my_tags)

    async def test_second_call_is_noop(self, database):
        await database.remove_my_tag_from_track("1", "t1")
        result = await database.remove_my_tag_from_track("1", "t1")
        assert result["removed"] is False

    async def test_never_raises_for_unknown_ids(self, database):
        result = await database.remove_my_tag_from_track("9999", "nonexistent")
        assert result["removed"] is False


class TestGetAvailableColors:
    async def test_lists_colors(self, database):
        colors = await database.get_available_colors()
        names = [c["name"] for c in colors]
        assert "Rose" in names
        assert "Red" in names


class TestGetMyTags:
    async def test_lists_groups_and_tags(self, database):
        tags = await database.get_my_tags()
        by_id = {t.id: t for t in tags}
        assert by_id["g1"].is_group is True
        assert by_id["g1"].parent_id is None
        assert by_id["t1"].is_group is False
        assert by_id["t1"].parent_id == "g1"

    async def test_filters_deleted(self, database):
        tags = await database.get_my_tags()
        ids = {t.id for t in tags}
        assert "t9" not in ids


class TestGetTrackMyTags:
    async def test_returns_assigned_tags(self, database):
        tags = await database.get_track_my_tags("1")
        assert len(tags) == 1
        assert tags[0].id == "t1"
        assert tags[0].name == "House"
        assert tags[0].is_group is False

    async def test_no_tags_for_untagged_track(self, database):
        tags = await database.get_track_my_tags("2")
        assert tags == []

    async def test_unknown_track_returns_empty(self, database):
        tags = await database.get_track_my_tags("9999")
        assert tags == []


class TestContentToTrackColor:
    def test_populates_color_name_from_relation(self, database):
        content = MockContent(
            ID=42, Title="Colored Track", Color=MockColor(ID="2", Commnt="Rose")
        )
        track = database._content_to_track(content)
        assert track.color == "Rose"

    def test_no_color_when_relation_absent(self, database):
        content = MockContent(ID=43, Title="No Color Track")
        track = database._content_to_track(content)
        assert track.color is None
