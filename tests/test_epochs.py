# clockapp/tests/test_epochs.py
import pytest
from clockapp.data.epochs import get_eras_for_year, format_era_display


class TestGetErasForYear:

    def test_year_with_multiple_overlapping_eras_sorted_by_weight(self, mock_eras):
        result = get_eras_for_year(1050)
        assert len(result) == 2
        assert result[0]["name"] == "High Middle Ages"
        assert result[1]["name"] == "Viking Age"
        weights = [e["weight"] for e in result]
        assert weights == sorted(weights, reverse=True)

    def test_year_zero_returns_matching_eras(self, mock_eras):
        result = get_eras_for_year(0)
        names = [e["name"] for e in result]
        assert "Classical Antiquity" in names

    def test_year_2359_returns_far_future_eras(self, mock_eras):
        result = get_eras_for_year(2359)
        names = [e["name"] for e in result]
        assert "Space Age" in names
        assert "Digital Age" in names
        assert result[0]["name"] == "Digital Age"  # weight 7 > 6

    def test_year_with_no_matching_era_returns_empty_list(self, mock_eras):
        result = get_eras_for_year(-9999)
        assert result == []

    def test_year_exactly_on_era_start_boundary(self, mock_eras):
        result = get_eras_for_year(793)
        names = [e["name"] for e in result]
        assert "Viking Age" in names

    def test_year_exactly_on_era_end_boundary(self, mock_eras):
        result = get_eras_for_year(1100)
        names = [e["name"] for e in result]
        assert "Viking Age" in names

    def test_year_one_past_era_end_boundary_excludes_era(self, mock_eras):
        result = get_eras_for_year(1101)
        names = [e["name"] for e in result]
        assert "Viking Age" not in names


class TestFormatEraDisplay:

    def test_top_two_eras_joined_with_slash(self, mock_eras):
        result = format_era_display(1050)
        assert result == "High Middle Ages / Viking Age"

    def test_single_era_has_no_separator(self, mock_eras):
        result = format_era_display(-500)
        assert result == "Classical Antiquity"
        assert " / " not in result

    def test_no_matching_eras_returns_empty_string(self, mock_eras):
        result = format_era_display(-9999)
        assert result == ""
        assert isinstance(result, str)
