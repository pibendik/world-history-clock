# clockapp/tests/test_fetcher.py
import pytest
import requests
from unittest.mock import MagicMock, patch
from clockapp.server.fetcher import _run_query, SPARQL_P585


class TestRunQueryFiltering:

    def _mock_response(self, bindings: list, status_ok: bool = True) -> MagicMock:
        resp = MagicMock()
        resp.ok = status_ok
        resp.json.return_value = {"results": {"bindings": bindings}}
        return resp

    def test_q_code_label_is_excluded(self):
        """Raw Q-code labels (unresolved by Wikidata label service) are filtered out."""
        bindings = [
            {"eventLabel": {"value": "Q12345678"}},
            {"eventLabel": {"value": "The signing of the Magna Carta at Runnymede"}},
        ]
        mock_resp = self._mock_response(bindings)
        with patch("clockapp.server.fetcher.requests.get", return_value=mock_resp):
            result = _run_query(SPARQL_P585, year=1215)
        assert "Q12345678" not in result
        assert "The signing of the Magna Carta at Runnymede" in result

    def test_short_label_excluded(self):
        """Labels shorter than 20 characters are filtered out (calendar boilerplate, etc.)."""
        bindings = [
            {"eventLabel": {"value": "January"}},  # 7 chars: excluded
            {"eventLabel": {"value": "Norman Conquest of England 1066"}},  # included
        ]
        mock_resp = self._mock_response(bindings)
        with patch("clockapp.server.fetcher.requests.get", return_value=mock_resp):
            result = _run_query(SPARQL_P585, year=1066)
        assert "January" not in result
        assert "Norman Conquest of England 1066" in result

    def test_valid_event_passes_through_filter(self):
        """A well-formed, long-enough label is returned unchanged."""
        label = "Construction of the Great Wall of China began"
        bindings = [{"eventLabel": {"value": label}}]
        mock_resp = self._mock_response(bindings)
        with patch("clockapp.server.fetcher.requests.get", return_value=mock_resp):
            result = _run_query(SPARQL_P585, year=-221)
        assert result == [label]

    def test_non_ok_http_response_returns_empty_list(self):
        """HTTP 429 / any non-OK response returns [] without raising."""
        mock_resp = self._mock_response([], status_ok=False)
        mock_resp.ok = False
        with patch("clockapp.server.fetcher.requests.get", return_value=mock_resp):
            result = _run_query(SPARQL_P585, year=1969)
        assert result == []

    def test_network_timeout_returns_empty_list(self):
        """requests.Timeout is swallowed; returns [] without raising."""
        with patch(
            "clockapp.server.fetcher.requests.get",
            side_effect=requests.exceptions.Timeout,
        ):
            result = _run_query(SPARQL_P585, year=1969)
        assert result == []
