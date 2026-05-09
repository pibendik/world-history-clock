# clockapp/tests/test_wikipedia_fetcher.py
import pytest
import requests
from unittest.mock import MagicMock, patch

from clockapp.server.fetcher import (
    _clean_wikitext,
    _wikipedia_article_title,
    fetch_wikipedia_events,
)


class TestWikipediaArticleTitle:

    def test_year_1000_and_above_returns_plain_number(self):
        assert _wikipedia_article_title(1969) == "1969"
        assert _wikipedia_article_title(1000) == "1000"
        assert _wikipedia_article_title(2100) == "2100"

    def test_year_1_to_999_returns_ad_suffix(self):
        assert _wikipedia_article_title(500) == "500 AD"
        assert _wikipedia_article_title(1) == "1 AD"
        assert _wikipedia_article_title(999) == "999 AD"

    def test_year_zero_returns_none(self):
        assert _wikipedia_article_title(0) is None

    def test_negative_year_returns_none(self):
        assert _wikipedia_article_title(-100) is None

    def test_year_above_2100_returns_none(self):
        assert _wikipedia_article_title(2101) is None
        assert _wikipedia_article_title(2359) is None


class TestCleanWikitext:

    def test_strips_ref_tags(self):
        text = "Some event<ref>Citation needed</ref> happened"
        assert "ref" not in _clean_wikitext(text)
        assert "Citation needed" not in _clean_wikitext(text)

    def test_resolves_piped_wiki_links(self):
        text = "[[Battle of Hastings|The Norman Conquest]] began"
        assert _clean_wikitext(text) == "The Norman Conquest began"

    def test_resolves_plain_wiki_links(self):
        text = "[[Julius Caesar]] was assassinated"
        assert _clean_wikitext(text) == "Julius Caesar was assassinated"

    def test_removes_templates(self):
        text = "Event {{flagicon|England}} in England"
        assert "{{" not in _clean_wikitext(text)
        assert "flagicon" not in _clean_wikitext(text)

    def test_removes_nested_templates(self):
        text = "{{outer|{{inner|value}}}} some text"
        result = _clean_wikitext(text)
        assert "{{" not in result
        assert "some text" in result

    def test_strips_bold_markup(self):
        text = "'''Important''' event occurred"
        assert _clean_wikitext(text) == "Important event occurred"

    def test_replaces_html_entities(self):
        text = "Years 1939&ndash;1945 &amp; beyond"
        result = _clean_wikitext(text)
        assert "–" in result
        assert "&" in result
        assert "&ndash;" not in result
        assert "&amp;" not in result

    def test_strips_leading_date_prefix_with_dash(self):
        text = "January 4 – The treaty was signed"
        assert _clean_wikitext(text) == "The treaty was signed"

    def test_strips_leading_dash_without_date(self):
        text = "– An event occurs"
        assert _clean_wikitext(text) == "An event occurs"

    def test_plain_text_unchanged(self):
        text = "The Ottoman Empire reaches its greatest extent"
        assert _clean_wikitext(text) == text

    def test_strips_html_tags(self):
        text = "Event <span class='year'>1969</span> happened"
        assert "<span" not in _clean_wikitext(text)
        assert "1969" in _clean_wikitext(text)


class TestFetchWikipediaEvents:

    def _mock_query_response(self, wikitext: str, pageid: int = 12345) -> MagicMock:
        resp = MagicMock()
        resp.ok = True
        resp.json.return_value = {
            "query": {
                "pages": {
                    str(pageid): {
                        "pageid": pageid,
                        "revisions": [{"slots": {"main": {"*": wikitext}}}],
                    }
                }
            }
        }
        return resp

    def test_returns_empty_for_out_of_range_year(self):
        """No HTTP calls should be made for year 0 or negative years."""
        with patch("clockapp.server.fetcher.requests.get") as mock_get:
            result = fetch_wikipedia_events(0)
        assert result == []
        mock_get.assert_not_called()

    def test_returns_empty_for_future_year_above_2100(self):
        with patch("clockapp.server.fetcher.requests.get") as mock_get:
            result = fetch_wikipedia_events(2359)
        assert result == []
        mock_get.assert_not_called()

    def test_returns_empty_on_http_error(self):
        mock_bad = MagicMock()
        mock_bad.ok = False
        with patch("clockapp.server.fetcher.requests.get", return_value=mock_bad):
            result = fetch_wikipedia_events(1969)
        assert result == []

    def test_returns_empty_on_network_error(self):
        with patch(
            "clockapp.server.fetcher.requests.get",
            side_effect=requests.exceptions.Timeout,
        ):
            result = fetch_wikipedia_events(1969)
        assert result == []

    def test_parses_bullet_events_from_wikitext(self):
        wikitext = (
            "==Events==\n"
            "* [[Battle of Hastings]] – William the Conqueror defeats Harold\n"
            "* Another significant event occurred in this year\n"
        )
        mock_resp = self._mock_query_response(wikitext)
        with patch("clockapp.server.fetcher.requests.get", return_value=mock_resp):
            result = fetch_wikipedia_events(1066)
        assert len(result) >= 1
        assert any("William the Conqueror" in e or "Battle of Hastings" in e for e in result)

    def test_returns_empty_when_no_events_section(self):
        """If article has no Events section and no bullets, return []."""
        wikitext = "== Deaths ==\nSome content without bullet points.\n"
        mock_resp = self._mock_query_response(wikitext)
        with patch("clockapp.server.fetcher.requests.get", return_value=mock_resp):
            result = fetch_wikipedia_events(1066)
        assert isinstance(result, list)

    def test_returns_empty_for_missing_article(self):
        """pageid -1 means article not found."""
        resp = MagicMock()
        resp.ok = True
        resp.json.return_value = {
            "query": {"pages": {"-1": {"pageid": -1}}}
        }
        with patch("clockapp.server.fetcher.requests.get", return_value=resp):
            result = fetch_wikipedia_events(1066)
        assert result == []

    def test_short_events_excluded(self):
        """Events shorter than 20 chars are filtered by _is_interesting_label."""
        wikitext = (
            "==Events==\n"
            "* Short\n"
            "* This is a sufficiently long event description that passes filter\n"
        )
        mock_resp = self._mock_query_response(wikitext)
        with patch("clockapp.server.fetcher.requests.get", return_value=mock_resp):
            result = fetch_wikipedia_events(1969)
        assert "Short" not in result
        assert any("sufficiently long" in e for e in result)

    def test_handles_redirect_articles(self):
        """Early year articles like '701 AD' redirect to '701' — should still work."""
        wikitext = (
            "==Events==\n"
            "* Battle of Some Place: An important medieval battle was fought here\n"
        )
        mock_resp = self._mock_query_response(wikitext)
        with patch("clockapp.server.fetcher.requests.get", return_value=mock_resp):
            result = fetch_wikipedia_events(701)
        assert len(result) >= 1
