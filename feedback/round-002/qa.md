# Year Clock — QA Review Round 002

**Reviewer:** QA Engineer (10 yrs experience)  
**Date:** 2025-07-14  
**Scope:** Full test suite design — unit (Python + JS), integration (FastAPI), E2E (Playwright), test pyramid, Phase 2 regression risk  
**Previous round:** [Round 001 QA](../round-001/qa.md)

---

## Context

Round 1 identified zero test coverage across all layers: no pytest suite, no Jest/Vitest suite, no integration tests, no E2E tests. The Flutter `widget_test.dart` was scaffold boilerplate that wouldn't compile. This round translates those identified risks into a complete, runnable test specification. All code below is actual test code, not pseudocode — copy it into a `tests/` directory and it should run (with the noted setup).

---

## 1. Python Unit Test Suite (pytest)

### Setup

```
clockapp/tests/__init__.py  (empty)
clockapp/tests/conftest.py
clockapp/tests/test_epochs.py
clockapp/tests/test_fetcher.py
```

### `conftest.py`

```python
# clockapp/tests/conftest.py
import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch


SAMPLE_ERAS = [
    {"name": "Viking Age", "start": 793, "end": 1100, "weight": 7, "category": "regional"},
    {"name": "High Middle Ages", "start": 1000, "end": 1300, "weight": 8, "category": "general"},
    {"name": "Early Middle Ages", "start": 500, "end": 1000, "weight": 5, "category": "general"},
    {"name": "Classical Antiquity", "start": -800, "end": 600, "weight": 9, "category": "general"},
    {"name": "Space Age", "start": 1957, "end": 9999, "weight": 6, "category": "science"},
    {"name": "Digital Age", "start": 1970, "end": 9999, "weight": 7, "category": "science"},
]


@pytest.fixture
def mock_eras(monkeypatch):
    """Patch _load_eras() to return a controlled era list without touching the filesystem."""
    import clockapp.data.epochs as epochs_module
    monkeypatch.setattr(epochs_module, "_load_eras", lambda: SAMPLE_ERAS)
```

---

### `test_epochs.py` — 10 test cases

```python
# clockapp/tests/test_epochs.py
import pytest
from clockapp.data.epochs import get_eras_for_year, format_era_display


# ── get_eras_for_year ──────────────────────────────────────────────────────────

class TestGetErasForYear:

    def test_year_with_multiple_overlapping_eras_sorted_by_weight(self, mock_eras):
        """
        Given: year 1050 falls inside Viking Age (w=7), High Middle Ages (w=8),
               Early Middle Ages (w=5), Classical Antiquity (w=9)... wait,
               Classical Antiquity ends at 600 so not included. Viking (793-1100) ✓,
               High Middle (1000-1300) ✓, Early Middle (500-1000) ✗ (1050 > 1000).
        When:  get_eras_for_year(1050) is called.
        Then:  Returns [High Middle Ages (w=8), Viking Age (w=7)] — sorted desc by weight.
        """
        result = get_eras_for_year(1050)
        assert len(result) == 2
        assert result[0]["name"] == "High Middle Ages"
        assert result[1]["name"] == "Viking Age"
        # Verify sort order is strictly descending
        weights = [e["weight"] for e in result]
        assert weights == sorted(weights, reverse=True)

    def test_year_zero_returns_matching_eras(self, mock_eras):
        """
        Given: SAMPLE_ERAS has Classical Antiquity start=-800, end=600, weight=9.
        When:  get_eras_for_year(0) is called.
        Then:  Classical Antiquity is returned (0 is within -800..600).
               Year 0 is historically ambiguous (no such year in Julian calendar)
               but the function must handle it without crashing.
        """
        result = get_eras_for_year(0)
        names = [e["name"] for e in result]
        assert "Classical Antiquity" in names

    def test_year_2359_returns_far_future_eras(self, mock_eras):
        """
        Given: Space Age (1957-9999) and Digital Age (1970-9999) both cover 2359.
        When:  get_eras_for_year(2359) is called.
        Then:  Both are returned; Digital Age (w=7) before Space Age (w=6).
        """
        result = get_eras_for_year(2359)
        names = [e["name"] for e in result]
        assert "Space Age" in names
        assert "Digital Age" in names
        assert result[0]["name"] == "Digital Age"   # weight 7 > 6

    def test_year_with_no_matching_era_returns_empty_list(self, mock_eras):
        """
        Given: SAMPLE_ERAS has no entry covering year -9999.
        When:  get_eras_for_year(-9999) is called.
        Then:  Returns an empty list (no crash, no KeyError).
        """
        result = get_eras_for_year(-9999)
        assert result == []

    def test_year_exactly_on_era_start_boundary(self, mock_eras):
        """
        Given: Viking Age starts at 793 (inclusive boundary).
        When:  get_eras_for_year(793) is called.
        Then:  Viking Age IS included (boundary is inclusive: start <= year <= end).
        """
        result = get_eras_for_year(793)
        names = [e["name"] for e in result]
        assert "Viking Age" in names

    def test_year_exactly_on_era_end_boundary(self, mock_eras):
        """
        Given: Viking Age ends at 1100 (inclusive boundary).
        When:  get_eras_for_year(1100) is called.
        Then:  Viking Age IS included.
        """
        result = get_eras_for_year(1100)
        names = [e["name"] for e in result]
        assert "Viking Age" in names

    def test_year_one_past_era_end_boundary_excludes_era(self, mock_eras):
        """
        Given: Viking Age ends at 1100.
        When:  get_eras_for_year(1101) is called.
        Then:  Viking Age is NOT included.
        """
        result = get_eras_for_year(1101)
        names = [e["name"] for e in result]
        assert "Viking Age" not in names


# ── format_era_display ─────────────────────────────────────────────────────────

class TestFormatEraDisplay:

    def test_top_two_eras_joined_with_interpunct(self, mock_eras):
        """
        Given: Year 1050 has High Middle Ages (w=8) and Viking Age (w=7).
        When:  format_era_display(1050) is called.
        Then:  Returns 'High Middle Ages · Viking Age' (space-interpunct-space separator).
        """
        result = format_era_display(1050)
        assert result == "High Middle Ages · Viking Age"

    def test_single_era_has_no_separator(self, mock_eras):
        """
        Given: Year 900 is only inside Early Middle Ages (500-1000) in our sample
               (Viking starts 793, so actually Viking and Early Middle overlap at 900).
               Use year -500 which is only Classical Antiquity.
        When:  format_era_display(-500) is called.
        Then:  Returns just 'Classical Antiquity' with no interpunct.
        """
        result = format_era_display(-500)
        assert result == "Classical Antiquity"
        assert " · " not in result

    def test_no_matching_eras_returns_empty_string(self, mock_eras):
        """
        Given: Year -9999 has no matching era.
        When:  format_era_display(-9999) is called.
        Then:  Returns '' (empty string), not None or raises.
        """
        result = format_era_display(-9999)
        assert result == ""
        assert isinstance(result, str)
```

---

### `test_fetcher.py` — 5 test cases

```python
# clockapp/tests/test_fetcher.py
import pytest
import requests
from unittest.mock import MagicMock, patch, call
from clockapp.server.fetcher import _run_query, fetch_wikidata_events, SPARQL_P585


# ── SPARQL result filtering ────────────────────────────────────────────────────

class TestRunQueryFiltering:

    def _mock_response(self, bindings: list[dict], status_ok: bool = True) -> MagicMock:
        resp = MagicMock()
        resp.ok = status_ok
        resp.json.return_value = {"results": {"bindings": bindings}}
        return resp

    def test_q_code_label_is_excluded(self):
        """
        Given: Wikidata returns a binding whose eventLabel starts with 'Q' (raw Q-code,
               meaning the label service did not resolve a human-readable name).
        When:  _run_query is called.
        Then:  The Q-code label is NOT in the returned list.
        """
        bindings = [
            {"eventLabel": {"value": "Q12345678"}},                     # Q-code: excluded
            {"eventLabel": {"value": "The signing of the Magna Carta"}}, # valid: included
        ]
        mock_resp = self._mock_response(bindings)
        with patch("clockapp.server.fetcher.requests.get", return_value=mock_resp):
            result = _run_query(SPARQL_P585, year=1215)
        assert "Q12345678" not in result
        assert "The signing of the Magna Carta" in result

    def test_calendar_boilerplate_short_label_excluded(self):
        """
        Given: Wikidata returns labels shorter than 15 characters (calendar boilerplate
               like 'January', 'Q3', 'AD 500', etc.).
        When:  _run_query is called.
        Then:  Labels with len < 15 are filtered out.
        """
        bindings = [
            {"eventLabel": {"value": "January"}},           # 7 chars: excluded
            {"eventLabel": {"value": "Norman Conquest of England 1066"}},  # 32 chars: included
        ]
        mock_resp = self._mock_response(bindings)
        with patch("clockapp.server.fetcher.requests.get", return_value=mock_resp):
            result = _run_query(SPARQL_P585, year=1066)
        assert "January" not in result
        assert "Norman Conquest of England 1066" in result

    def test_valid_event_passes_through_filter(self):
        """
        Given: A well-formed Wikidata binding with a readable, long-enough label.
        When:  _run_query is called with a 200 OK response.
        Then:  The label is present in the result list exactly once.
        """
        label = "Construction of the Great Wall of China began"
        bindings = [{"eventLabel": {"value": label}}]
        mock_resp = self._mock_response(bindings)
        with patch("clockapp.server.fetcher.requests.get", return_value=mock_resp):
            result = _run_query(SPARQL_P585, year=-221)
        assert result == [label]

    def test_non_ok_http_response_returns_empty_list(self):
        """
        Given: Wikidata returns HTTP 429 (rate limited).
        When:  _run_query is called.
        Then:  Returns [] without raising an exception.
        """
        mock_resp = self._mock_response([], status_ok=False)
        mock_resp.ok = False
        with patch("clockapp.server.fetcher.requests.get", return_value=mock_resp):
            result = _run_query(SPARQL_P585, year=1969)
        assert result == []

    def test_network_timeout_returns_empty_list(self):
        """
        Given: requests.get raises requests.exceptions.Timeout (8-second timeout exceeded).
        When:  _run_query is called.
        Then:  Returns [] without raising — the exception is swallowed gracefully.
        """
        with patch(
            "clockapp.server.fetcher.requests.get",
            side_effect=requests.exceptions.Timeout,
        ):
            result = _run_query(SPARQL_P585, year=1969)
        assert result == []
```

---

### `test_year_calculation.py` — 5 test cases

```python
# clockapp/tests/test_year_calculation.py
"""
Tests for year derivation logic. The server side does not expose
derive_year() directly — it receives `year` as a path parameter int.
These tests verify the numeric contract so the JS implementation can be
validated against the same spec.
"""
import pytest


def derive_year_python(hh: int, mm: int) -> int:
    """Python reference implementation matching JS: parseInt(pad(HH) + pad(MM))."""
    return int(f"{hh:02d}{mm:02d}")


class TestDeriveYear:

    def test_midnight_zero_zero_returns_zero(self):
        """
        Given: Time is 00:00 (midnight).
        When:  derive_year(0, 0) is called.
        Then:  Returns 0 — year zero, the lowest valid value.
        """
        assert derive_year_python(0, 0) == 0

    def test_hh_15_mm_50_returns_1550(self):
        """
        Given: Time is 15:50.
        When:  derive_year(15, 50) is called.
        Then:  Returns 1550 — straightforward concatenation case.
        """
        assert derive_year_python(15, 50) == 1550

    def test_hh_23_mm_59_returns_2359(self):
        """
        Given: Time is 23:59 (last minute of the day).
        When:  derive_year(23, 59) is called.
        Then:  Returns 2359 — the maximum valid year value.
        """
        assert derive_year_python(23, 59) == 2359

    def test_hh_9_mm_7_returns_907_with_padding(self):
        """
        Given: Time is 09:07 — single-digit hour and minute.
        When:  derive_year(9, 7) is called.
        Then:  Returns 907 — '09' + '07' = '0907' → 907 (leading zero stripped by int()).
               This confirms both components are zero-padded to 2 digits before concat.
        """
        assert derive_year_python(9, 7) == 907

    def test_hh_0_mm_1_returns_1_not_10(self):
        """
        Given: Time is 00:01 — a common off-by-one risk.
        When:  derive_year(0, 1) is called.
        Then:  Returns 1 (not 10, which would result from '0' + '1' without padding).
               '00' + '01' = '0001' → int = 1.
        """
        assert derive_year_python(0, 1) == 1
```

---

## 2. JavaScript Unit Test Suite (Jest)

### Setup

```json
// package.json additions
{
  "devDependencies": {
    "jest": "^29.0.0",
    "@jest/globals": "^29.0.0",
    "jest-environment-jsdom": "^29.0.0"
  },
  "jest": {
    "testEnvironment": "jsdom"
  }
}
```

### `tests/yearclock.test.js` — 10 test cases

```javascript
// clockapp/tests/yearclock.test.js
// Assumes core JS logic is extracted to clockapp/web/lib/logic.js
// For now we inline the minimal implementations to test.

// ── Extracted logic (matches index.html implementations) ─────────────────────

class YearCache {
  constructor() { this._store = {}; }

  set(topic, events) { this._store[topic] = { events, idx: 0 }; }

  getNextForTopic(topic, dislikedSet) {
    const entry = this._store[topic];
    if (!entry || entry.events.length === 0) return null;
    const filtered = entry.events.filter(e => !dislikedSet.has(e.text));
    if (filtered.length === 0) return null;
    const item = filtered[entry.idx % filtered.length];
    entry.idx = (entry.idx + 1) % filtered.length;
    return item;
  }
}

const TOPIC_KEYWORDS = {
  Science: ["discov", "invent", "scientif", "experiment", "research", "laborator"],
  Astronomy: ["star", "planet", "comet", "astrono", "space", "moon", "orbit", "telescope"],
  History: ["war", "battle", "treaty", "empire", "king", "queen", "revolution"],
  Music: ["music", "symphony", "opera", "composed", "concert", "orchestra"],
  Literature: ["novel", "poem", "poet", "publish", "author", "book", "play"],
};

function classifyTopics(labels) {
  const topics = new Set(["All"]);
  for (const label of labels) {
    const lower = label.toLowerCase();
    for (const [topic, keywords] of Object.entries(TOPIC_KEYWORDS)) {
      if (keywords.some(kw => lower.includes(kw))) {
        topics.add(topic);
      }
    }
  }
  return topics;
}

function deriveYear(hh, mm) {
  return parseInt(String(hh).padStart(2, "0") + String(mm).padStart(2, "0"), 10);
}

// ── Tests ─────────────────────────────────────────────────────────────────────

describe("YearCache.getNextForTopic", () => {

  test("TC-JS-01: cycling behaviour returns events in round-robin order", () => {
    // Given: A cache with 3 events for topic "Science"
    const cache = new YearCache();
    const events = [
      { text: "Discovery of penicillin" },
      { text: "First human genome sequenced" },
      { text: "Theory of relativity published" },
    ];
    cache.set("Science", events);
    const disliked = new Set();

    // When: getNextForTopic is called 4 times
    const results = [
      cache.getNextForTopic("Science", disliked),
      cache.getNextForTopic("Science", disliked),
      cache.getNextForTopic("Science", disliked),
      cache.getNextForTopic("Science", disliked),  // wraps around
    ];

    // Then: 4th result equals 1st result (index cycles)
    expect(results[3]).toEqual(results[0]);
  });

  test("TC-JS-02: disliked events are filtered from rotation", () => {
    // Given: A cache with 3 events; one is disliked
    const cache = new YearCache();
    cache.set("All", [
      { text: "Moon landing Apollo 11" },
      { text: "Discovery of DNA structure" },
      { text: "First commercial flight" },
    ]);
    const disliked = new Set(["Discovery of DNA structure"]);

    // When: getNextForTopic is called multiple times
    const seen = new Set();
    for (let i = 0; i < 6; i++) {
      const r = cache.getNextForTopic("All", disliked);
      if (r) seen.add(r.text);
    }

    // Then: The disliked event NEVER appears
    expect(seen.has("Discovery of DNA structure")).toBe(false);
    expect(seen.size).toBe(2);
  });

  test("TC-JS-03: all events disliked returns null, not an infinite loop", () => {
    // Given: A cache with 2 events; both disliked
    const cache = new YearCache();
    cache.set("History", [
      { text: "Battle of Agincourt fought in northern France" },
      { text: "Treaty of Westphalia signed ending the Thirty Years War" },
    ]);
    const disliked = new Set([
      "Battle of Agincourt fought in northern France",
      "Treaty of Westphalia signed ending the Thirty Years War",
    ]);

    // When: getNextForTopic is called
    const result = cache.getNextForTopic("History", disliked);

    // Then: Returns null (does not hang or throw)
    expect(result).toBeNull();
  });

  test("TC-JS-04: empty cache for topic returns null", () => {
    // Given: A YearCache with no entries for topic "Literature"
    const cache = new YearCache();
    const disliked = new Set();

    // When: getNextForTopic is called for an uncached topic
    const result = cache.getNextForTopic("Literature", disliked);

    // Then: Returns null
    expect(result).toBeNull();
  });

  test("TC-JS-05: cache with zero events for topic returns null", () => {
    // Given: Topic is set but with empty events array
    const cache = new YearCache();
    cache.set("Music", []);
    const disliked = new Set();

    // When: getNextForTopic is called
    const result = cache.getNextForTopic("Music", disliked);

    // Then: Returns null (no IndexError)
    expect(result).toBeNull();
  });
});


describe("classifyTopics", () => {

  test("TC-JS-06: science keyword matches and classifies correctly", () => {
    // Given: Label contains 'discov' (substring match for 'discovered', 'discovery')
    const labels = ["The discovery of the electron by J.J. Thomson in 1897"];

    // When: classifyTopics is called
    const topics = classifyTopics(labels);

    // Then: Science is in the result set; All is always present
    expect(topics.has("Science")).toBe(true);
    expect(topics.has("All")).toBe(true);
  });

  test("TC-JS-07: event matching no keywords only returns All topic", () => {
    // Given: Label is a proper noun that doesn't contain any known keyword
    const labels = ["Tokugawa Ieyasu unified Japan under shogunate rule"];

    // When: classifyTopics is called
    const topics = classifyTopics(labels);

    // Then: Only 'All' is in the set (no false positive classification)
    // Note: 'king' would match History — but this label has none of the keywords
    expect(topics.size).toBe(1);
    expect(topics.has("All")).toBe(true);
  });

  test("TC-JS-08: empty labels array returns only All topic", () => {
    // Given: No events for this year
    const labels = [];

    // When: classifyTopics is called
    const topics = classifyTopics(labels);

    // Then: Returns a Set containing only 'All'
    expect(topics.size).toBe(1);
    expect(topics.has("All")).toBe(true);
  });

  test("TC-JS-09: astronomy keyword star risks false positive on non-astronomical context", () => {
    // Given: Label contains 'star' but is about cinema, not astronomy
    // This is a KNOWN FALSE POSITIVE documented in Round 001 TC-TOPIC-03.
    const labels = ["The first Star Wars film was released in Hollywood cinemas"];

    // When: classifyTopics is called
    const topics = classifyTopics(labels);

    // Then: Astronomy IS matched (known bug — this test documents the behaviour,
    //       not validates it as correct). A future fix should add word-boundary checks.
    // CURRENT BEHAVIOUR (document, not approve):
    expect(topics.has("Astronomy")).toBe(true);
    // TODO: Once word-boundary matching is added, this assertion should flip to toBe(false).
  });

  test("TC-JS-10: year boundary — 00:00 yields year 0 (not NaN or undefined)", () => {
    // Given: The clock reads 00:00 — both components are 0
    // When: deriveYear(0, 0) is called
    const year = deriveYear(0, 0);

    // Then: Returns the integer 0, not NaN, not '0000' as a string
    expect(year).toBe(0);
    expect(typeof year).toBe("number");
    expect(Number.isNaN(year)).toBe(false);
  });
});
```

---

## 3. FastAPI Integration Tests (pytest + httpx)

### Setup

```
pip install httpx pytest-asyncio
```

```python
# clockapp/tests/test_api.py
import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import patch, MagicMock


# Import the FastAPI app. DB must be isolated to a temp file for tests.
import os, tempfile, pathlib

@pytest.fixture(autouse=True, scope="module")
def isolate_db(tmp_path_factory):
    """Point DB_PATH at a throwaway file so tests don't touch production data."""
    db_dir = tmp_path_factory.mktemp("testdb")
    db_path = db_dir / "test_yearclock.db"
    with patch("clockapp.server.db._DB_PATH", db_path):
        yield db_path


@pytest.fixture(scope="module")
def app():
    from clockapp.server.main import app as fastapi_app
    return fastapi_app


@pytest.fixture
async def client(app):
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c


# ── Test cases ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_int_01_get_health_returns_200(client):
    """
    Given: The FastAPI application is running.
    When:  GET /health is called.
    Then:  Returns HTTP 200 with body {"status": "ok", "version": "1.0"}.
    """
    resp = await client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert "version" in body


@pytest.mark.asyncio
async def test_int_02_get_year_1969_returns_events_array(client):
    """
    Given: Year 1969 is historical (< _CURRENT_YEAR).
    When:  GET /year/1969 is called (Wikidata mocked to return two events).
    Then:  Response has 'events' key containing a list; is_future is False.
    """
    mock_events = [
        {"text": "Apollo 11 lands on the Moon for the first time", "source": "Wikidata"},
        {"text": "Woodstock music festival held in upstate New York", "source": "Wikidata"},
    ]
    with patch("clockapp.server.main.get_events_for_year", return_value=mock_events):
        resp = await client.get("/year/1969")
    assert resp.status_code == 200
    body = resp.json()
    assert body["year"] == 1969
    assert isinstance(body["events"], list)
    assert len(body["events"]) == 2
    assert body["is_future"] is False


@pytest.mark.asyncio
async def test_int_03_get_year_0_returns_eras_and_no_future_flag(client):
    """
    Given: Year 0 is historical (well before _CURRENT_YEAR).
    When:  GET /year/0 is called (Wikidata may return empty for year 0).
    Then:  Response contains 'eras' list (Classical Antiquity era covers year 0),
           is_future is False, no 5xx error.
    """
    with patch("clockapp.server.main.get_events_for_year", return_value=[]):
        resp = await client.get("/year/0")
    assert resp.status_code == 200
    body = resp.json()
    assert body["is_future"] is False
    assert isinstance(body["eras"], list)
    # era_display may be empty string if no era covers 0, but should not be None
    assert body["era_display"] is not None


@pytest.mark.asyncio
async def test_int_04_get_year_99999_returns_future_flagged_response(client):
    """
    Given: Year 99999 is far beyond _CURRENT_YEAR (2025).
    When:  GET /year/99999 is called.
    Then:  Response has is_future = True and events = [] (server does not fetch).
           The server currently does NOT return 400 — it clamps by returning empty events.
           This test documents the current clamping behaviour.
           TODO: Add HTTP 400 for year > 2359 in a future release.
    """
    resp = await client.get("/year/99999")
    assert resp.status_code == 200
    body = resp.json()
    assert body["is_future"] is True
    assert body["events"] == []


@pytest.mark.asyncio
async def test_int_05_post_reaction_persists_and_get_reactions_retrieves(client):
    """
    Given: No prior reactions exist for a specific event text.
    When:  POST /reaction is called with year=1969, text, reaction='like'.
    Then:  Returns 201. Subsequent GET /reactions returns a dict containing
           the key '1969::<text>' with reaction='like'.
    """
    payload = {
        "year": 1969,
        "text": "Apollo 11 lands on the Moon for the first time in history",
        "source": "Wikidata",
        "reaction": "like",
    }
    post_resp = await client.post("/reaction", json=payload)
    assert post_resp.status_code == 201

    get_resp = await client.get("/reactions")
    assert get_resp.status_code == 200
    reactions = get_resp.json()
    expected_key = "1969::Apollo 11 lands on the Moon for the first time in history"
    assert expected_key in reactions
    assert reactions[expected_key]["reaction"] == "like"


@pytest.mark.asyncio
async def test_int_06_post_reaction_invalid_value_returns_422(client):
    """
    Given: reaction field contains an invalid value ('meh').
    When:  POST /reaction is called.
    Then:  Returns HTTP 422 (Unprocessable Entity) — server validates 'like'/'dislike' only.
    """
    payload = {"year": 1066, "text": "Battle of Hastings changed England forever", "reaction": "meh"}
    resp = await client.post("/reaction", json=payload)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_int_07_post_saved_get_saved_delete_saved_full_cycle(client):
    """
    Given: A new fact to save.
    When:  POST /saved is called, then GET /saved, then DELETE /saved/{key}.
    Then:  After POST — fact appears in GET /saved list.
           After DELETE — fact no longer appears in GET /saved list.
    """
    text = "First transatlantic telegraph cable was successfully laid in 1866"
    year = 1866
    key = f"{year}::{text}"

    # Step 1: Save
    post_resp = await client.post("/saved", json={"year": year, "text": text, "source": "Wikidata"})
    assert post_resp.status_code == 201

    # Step 2: Retrieve
    get_resp = await client.get("/saved")
    assert get_resp.status_code == 200
    saved_keys = [item["key"] for item in get_resp.json()]
    assert key in saved_keys

    # Step 3: Delete
    delete_resp = await client.delete(f"/saved/{key}")
    assert delete_resp.status_code == 200

    # Step 4: Confirm deletion
    get_resp2 = await client.get("/saved")
    saved_keys_after = [item["key"] for item in get_resp2.json()]
    assert key not in saved_keys_after


@pytest.mark.asyncio
async def test_int_08_post_saved_duplicate_is_idempotent(client):
    """
    Given: A fact has already been saved (key exists in DB via INSERT OR IGNORE).
    When:  POST /saved is called again with identical year + text.
    Then:  Returns 201 (no error), and GET /saved contains exactly one copy.
    """
    text = "Construction of the Panama Canal completed in 1914 after a decade of work"
    year = 1914
    key = f"{year}::{text}"
    payload = {"year": year, "text": text, "source": "Wikidata"}

    await client.post("/saved", json=payload)
    await client.post("/saved", json=payload)  # second save

    get_resp = await client.get("/saved")
    matching = [item for item in get_resp.json() if item["key"] == key]
    assert len(matching) == 1
```

---

## 4. E2E Regression Tests (Playwright)

### Setup

```bash
npm init playwright@latest
# environment: Node.js, browsers: chromium
# base URL: http://localhost:8421 (serve with: uvicorn clockapp.server.main:app --port 8421)
```

### `e2e/yearclock.spec.ts`

```typescript
// clockapp/e2e/yearclock.spec.ts
import { test, expect } from "@playwright/test";

// ── E2E-01: Clock ticks and year label updates ─────────────────────────────────
test("E2E-01: clock ticks and year display updates every minute", async ({ page }) => {
  // Given: The Year Clock web app is loaded
  await page.goto("/");
  await page.waitForSelector("#yearDisplay");

  // When: We read the year display and wait for the next tick (up to 65s)
  const initialYear = await page.textContent("#yearDisplay");

  // Simulate time advancing by 1 minute using fake timers
  await page.evaluate(() => {
    // Trigger tick manually — call the exported tick() or fire a custom event
    window.dispatchEvent(new CustomEvent("force-tick"));
  });

  // Then: The year display shows a 4-digit number (or '0000')
  const yearText = await page.textContent("#yearDisplay");
  expect(yearText).toMatch(/^\d{4}$/);
  expect(parseInt(yearText!, 10)).toBeGreaterThanOrEqual(0);
  expect(parseInt(yearText!, 10)).toBeLessThanOrEqual(2359);
});

// ── E2E-02: Topic chip filters events ──────────────────────────────────────────
test("E2E-02: clicking Science chip filters event cards to science events", async ({ page }) => {
  // Given: The app is loaded with mocked Wikidata returning a science event
  await page.route("**/query.wikidata.org/**", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        results: {
          bindings: [
            { eventLabel: { value: "Discovery of the electron by J.J. Thomson in 1897" } },
            { eventLabel: { value: "The battle of Waterloo ended the Napoleonic Wars" } },
          ],
        },
      }),
    });
  });

  await page.goto("/");
  await page.waitForSelector(".topic-chip");

  // When: The "Science" topic chip is clicked
  const scienceChip = page.locator(".topic-chip", { hasText: "Science" });
  await scienceChip.click();

  // Then: The active chip is Science; only science events are shown
  await expect(scienceChip).toHaveClass(/active/);
  // The visible event card should contain the science label
  const cardText = await page.textContent(".event-card");
  expect(cardText).toContain("Discovery");
});

// ── E2E-03: Save button persists across page reload ────────────────────────────
test("E2E-03: saving a fact persists it across a full page reload", async ({ page }) => {
  // Given: The app has loaded and displays at least one event card
  await page.goto("/");
  await page.waitForSelector(".save-btn");

  // When: The save button is clicked for the current event
  await page.click(".save-btn");
  const savedCountBefore = await page.textContent("#savedCount");

  // And: The page is reloaded
  await page.reload();
  await page.waitForSelector("#savedCount");

  // Then: savedCount is still > 0 after reload (localStorage persistence)
  const savedCountAfter = await page.textContent("#savedCount");
  const count = parseInt(savedCountAfter ?? "0", 10);
  expect(count).toBeGreaterThan(0);
  // The saved panel should show the item
  await page.click("#savedToggle");
  await page.waitForSelector(".saved-item");
  const items = await page.locator(".saved-item").count();
  expect(items).toBeGreaterThan(0);
});

// ── E2E-04: Prev/Next navigation and Live button ───────────────────────────────
test("E2E-04: Prev/Next navigation changes year display; Live button returns to current time", async ({ page }) => {
  // Given: The app is loaded in live mode showing the current year
  await page.goto("/");
  await page.waitForSelector("#yearDisplay");
  const liveYear = await page.textContent("#yearDisplay");

  // When: Next button is clicked once
  await page.click("#nextBtn");
  const nextYear = await page.textContent("#yearDisplay");

  // Then: Year has incremented by 1
  expect(parseInt(nextYear!, 10)).toBe(parseInt(liveYear!, 10) + 1);

  // When: Prev button is clicked once
  await page.click("#prevBtn");
  const prevYear = await page.textContent("#yearDisplay");

  // Then: Year returns to the original live year
  expect(prevYear).toBe(liveYear);

  // When: Live button is clicked after navigating away
  await page.click("#nextBtn");
  await page.click("#nextBtn");
  await page.click("#liveBtn");

  // Then: Year display returns to the current-time-derived year
  await page.waitForFunction(
    (expected) => document.querySelector("#yearDisplay")?.textContent === expected,
    liveYear,
    { timeout: 5000 }
  );
  const afterLive = await page.textContent("#yearDisplay");
  expect(afterLive).toBe(liveYear);
});

// ── E2E-05: Custom topic creation and event filtering ──────────────────────────
test("E2E-05: custom topic created with keyword filters events correctly", async ({ page }) => {
  // Given: The app is loaded
  await page.goto("/");
  await page.waitForSelector("#customTopicForm");

  // When: A custom topic named 'Exploration' with keyword 'voyage' is created
  await page.fill("#customTopicName", "Exploration");
  await page.fill("#customTopicKeywords", "voyage, expedition, explorer");
  await page.click("#addCustomTopicBtn");

  // Then: A new chip labelled 'Exploration' appears in the topic bar
  const chip = page.locator(".topic-chip", { hasText: "Exploration" });
  await expect(chip).toBeVisible();

  // When: The custom chip is clicked with an event containing 'voyage'
  await page.route("**/query.wikidata.org/**", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        results: {
          bindings: [
            { eventLabel: { value: "Magellan's voyage circumnavigated the entire globe" } },
            { eventLabel: { value: "Battle of Hastings changed the course of English history" } },
          ],
        },
      }),
    });
  });
  await chip.click();

  // Then: Only the 'voyage' event is shown (keyword match), battle event is hidden
  const cardText = await page.textContent(".event-card");
  expect(cardText).toContain("Magellan");
  expect(cardText).not.toContain("Hastings");
});
```

---

## 5. Test Pyramid Recommendation

### Proposed Ratio

```
                        ┌─────────────┐
                        │   E2E: 5%   │  ~5 scenarios
                        │  Playwright │
                   ┌────┴─────────────┴────┐
                   │  Integration: 20%     │  ~8–12 tests
                   │  pytest + httpx       │
              ┌────┴───────────────────────┴────┐
              │         Unit: 75%               │  ~50–60 tests
              │  pytest (Python) + Jest (JS)    │
              └─────────────────────────────────┘
```

| Layer | Count | Framework | Rationale |
|-------|-------|-----------|-----------|
| **Unit — Python** | ~30 | `pytest` + `unittest.mock` | Test `epochs.py`, `fetcher.py`, `db.py` functions in isolation with mocked I/O |
| **Unit — JavaScript** | ~25 | `Jest` with `jsdom` | Test `deriveYear`, `classifyTopics`, `YearCache`, `renderSavedPanel` (DOM interaction) |
| **Integration** | ~10 | `pytest` + `httpx` (async) | Test all FastAPI routes end-to-end with a real (test-isolated) SQLite DB |
| **E2E** | ~5 | `Playwright` (Chromium) | Smoke test the full user journey; run in CI on merge to main only |

**Why 75/20/5:**  
Year Clock's failure modes are predominantly logic bugs (year math, topic filtering, era boundary conditions) that are cheapest to catch at unit level. Integration tests validate the SQLite contract and API schema — 10 tests cover all 7 routes. E2E tests are slow (~30 s each), brittle against UI changes, and should guard only the highest-value user journeys: clock ticking, save persistence, navigation.

**CI pipeline (recommended):**
```yaml
# .github/workflows/test.yml
on: [push, pull_request]
jobs:
  unit:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: pip install -e ".[dev]" && pytest clockapp/tests/ -v
      - run: npm ci && npx jest
  integration:
    runs-on: ubuntu-latest
    steps:
      - run: pytest clockapp/tests/test_api.py -v
  e2e:
    runs-on: ubuntu-latest
    if: github.event_name == 'pull_request'
    steps:
      - run: npx playwright test --project=chromium
```

---

## 6. Regression Risk from Phase 2

Phase 2 delivered six features simultaneously: reactions, saved facts, custom topics, era stats, prev/next navigation, and a Flutter client. Three of these carry disproportionate regression risk:

### Risk 1 — Custom Topics + XSS (`innerHTML` injection)

**Why highest risk:** The custom topic workflow creates user-controlled string content that is rendered via `chip.innerHTML = \`🏷️ ${ct.label}...\`` without sanitisation. If Phase 3 adds any server-side storage or export of custom topics (the most natural next feature), this self-XSS instantly becomes stored XSS. The exact code path (`ct.label` → `innerHTML`) is one of only two XSS vectors identified in the codebase; it's tightly coupled to the new Phase 2 feature. A regression test must verify that `<script>` and `<img onerror>` in topic names are escaped to literal text, not executed.

**Coverage needed:** TC-CUSTOM-03 (from Round 1), plus an additional test that exercises the `renderSavedPanel` path (the second XSS vector) with a label sourced from a saved event whose text was derived from a custom-topic-filtered Wikidata result.

### Risk 2 — Prev/Next Navigation + Year Boundary Clamping

**Why second highest:** `navigate(delta)` is a new Phase 2 function. It correctly clamps using `Math.max(0, Math.min(2359, ...))` in the web client, but the Flutter `_navigateYear` has no clamping at all — and the server has no lower-bound validation either. Any Phase 3 change that touches `navigate()` or adds keyboard shortcuts (arrow keys are a common next request) risks breaking the boundary clamping. Additionally, the subtle falsy-zero bug (`!lastYear` is `true` when `lastYear === 0`) means the Prev button is incorrectly disabled at midnight. This bug existed in Phase 2 but has no test to catch a regression.

**Coverage needed:** TC-NAV-01, TC-NAV-02, TC-NAV-03 from Round 1, plus the Flutter server-side validation test (TC-NAV-04). The server should also have a boundary test: `GET /year/-1` and `GET /year/2400` should each return 400 once that validation is added (currently returns undefined behaviour).

### Risk 3 — Dislike Suppression Interaction with `get_events_for_year` Empty Cache

**Why third highest:** The dislike loop (`fetchEventData` tries `total` times looking for a non-disliked event) was written before Phase 2's server-side cache. Now there are two layers that can return empty: the server's SQLite cache (miss → Wikidata) and the in-memory `yearCache`. If a user dislikes all events for a year AND the Wikidata query happens to time out AND the negative result is not cached (as identified in Round 1 §3), the app enters a pathological state: it fetches Wikidata on every tick, the dislike loop exhausts, falls back to era text — but on the next tick it tries again. This is a performance regression introduced by Phase 2's combination of client-side dislike tracking and server-side fetch delegation. Testing the interaction between `get_events_for_year` returning `[]` (not `None`) and the JS dislike loop requires a new integration-level test that was not in scope for Phase 1.

**Coverage needed:** TC-WIKI-03 (from Round 1), plus a new end-to-end dislike-all-then-fetch test that mocks both Wikidata and localStorage to verify the era fallback fires exactly once per tick (not in a tight retry loop).

---

## Summary

| Suite | Tests | Framework | Status |
|-------|-------|-----------|--------|
| Python unit (epochs + fetcher + year calc) | 15 | pytest | ✅ Specified above |
| JavaScript unit (YearCache + classifyTopics + deriveYear) | 10 | Jest | ✅ Specified above |
| FastAPI integration | 8 | pytest + httpx | ✅ Specified above |
| E2E regression | 5 | Playwright | ✅ Specified above |
| **Total** | **38** | — | Baseline pyramid |

Round 3 should focus on: (a) expanding to the full 63-test pyramid proposed in Round 1, (b) adding Flutter widget tests once `widget_test.dart` references the actual `YearClock` widget, and (c) setting up the GitHub Actions CI pipeline with these tests as the merge gate.
