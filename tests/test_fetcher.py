# clockapp/tests/test_fetcher.py
import pytest
import requests
from unittest.mock import MagicMock, patch
from clockapp.server.fetcher import _is_interesting_label


class TestIsInterestingLabel:

    def test_q_code_label_is_excluded(self):
        """Raw Q-code labels (unresolved by Wikidata label service) are filtered out."""
        assert not _is_interesting_label("Q12345678")

    def test_short_label_excluded(self):
        """Labels shorter than 20 characters are filtered out (calendar boilerplate, etc.)."""
        assert not _is_interesting_label("January")

    def test_single_word_excluded(self):
        """Labels with no space are excluded regardless of length."""
        assert not _is_interesting_label("Supercalifragilistic")

    def test_valid_event_passes_through(self):
        """A well-formed, long-enough label is accepted."""
        assert _is_interesting_label("The signing of the Magna Carta at Runnymede")

    def test_olympic_participation_excluded(self):
        """'X at the 1936 Summer Olympics' is boring sports participation data."""
        assert not _is_interesting_label("Poland at the 1936 Summer Olympics")

    def test_sports_season_excluded(self):
        """Season entries are boring."""
        assert not _is_interesting_label("1969-70 NBA season")

    def test_year_in_prefix_excluded(self):
        """'1969 in science' type entries are calendar meta-entries."""
        assert not _is_interesting_label("1969 in science")

    def test_pure_number_excluded(self):
        assert not _is_interesting_label("12345")

    def test_valid_historical_event(self):
        assert _is_interesting_label("Norman Conquest of England 1066")

    def test_eclipse_excluded(self):
        assert not _is_interesting_label("Solar eclipse of March 29, 1969")
