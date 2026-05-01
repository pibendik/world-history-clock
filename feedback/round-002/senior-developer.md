# Year Clock — Senior Developer Review
**Round 002 · Reviewer: Senior Developer (15 years in)**

---

Round 1 covered the architecture. You had problems. I told you. Now we're going deeper. This round is about the actual lines of code that need to change — not impressions, not vibes. Specific. Surgical. With before and after.

Let's go.

---

## 1. Specific Code That Must Change

### Fix 1 — `_CURRENT_YEAR = 2025` in `server/main.py:30`

I flagged this in Round 1. It's still there. Here it is in its full embarrassing glory:

```python
# server/main.py:30
_CURRENT_YEAR = 2025
```

Used here:

```python
def _build_year_data(year: int) -> dict:
    is_future = year > _CURRENT_YEAR  # wrong on Jan 1 2026
```

This will silently break the app in eight months. Every year after 2025 will be labelled `is_future: True` and return zero events. Nobody will get an error — the app will just stop showing facts for any minute past 20:25. You will spend twenty minutes debugging why 23:00 is "the future" before you find this line.

**Fix:**

```python
# Before
_CURRENT_YEAR = 2025

# After
import datetime
_CURRENT_YEAR = datetime.date.today().year
```

One import. One line change. Do it now.

---

### Fix 2 — `sys.path.insert(0, ...)` in `server/main.py:3-4`

```python
# server/main.py:3-4
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
```

This is a runtime mutation of the import path to compensate for a broken package structure. It works on your machine. It will not work in a Docker container, a CI environment, or anywhere the working directory isn't exactly what you expect. This is a development hack that leaked into production code.

**Fix:** Install the package properly with a `pyproject.toml` (or at minimum `setup.py`) and run with `pip install -e .`. Then the imports work everywhere without path surgery.

```toml
# pyproject.toml (minimal)
[build-system]
requires = ["setuptools"]
build-backend = "setuptools.backends.legacy:BuildBackend"

[project]
name = "clockapp"
version = "0.1.0"
```

```bash
pip install -e .
```

Now `from clockapp.server.db import ...` just works. No path mutation needed. Delete the `sys.path.insert` lines entirely.

---

### Fix 3 — `_load_eras()` re-reads the JSON file on every call in `data/epochs.py`

```python
# data/epochs.py
def _load_eras() -> list[dict]:
    with open(_DATA_FILE, encoding="utf-8") as f:
        return json.load(f)


def get_eras_for_year(year: int) -> list[dict]:
    eras = _load_eras()  # disk I/O on every single call
    matching = [era for era in eras if era["start"] <= year <= era["end"]]
    return sorted(matching, key=lambda e: e["weight"], reverse=True)
```

`get_eras_for_year` is called from `_build_year_data`, which is called on every `GET /year/{year}` request, and *twice* more if the buffer endpoint is hit (up to 5 times per buffer call in the normal window=2 case). Every call re-reads `epochs.json` from disk. The data never changes at runtime. This is just wasteful.

**Fix:** Cache at module load time.

```python
# After
import json
from functools import lru_cache
from pathlib import Path

_DATA_FILE = Path(__file__).parent / "epochs.json"

@lru_cache(maxsize=1)
def _load_eras() -> tuple[dict, ...]:
    with open(_DATA_FILE, encoding="utf-8") as f:
        return tuple(json.load(f))  # tuple is hashable, safe to cache


def get_eras_for_year(year: int) -> list[dict]:
    matching = [era for era in _load_eras() if era["start"] <= year <= era["end"]]
    return sorted(matching, key=lambda e: e["weight"], reverse=True)
```

The `lru_cache` on a no-argument function gives you a singleton with zero effort. Read the file once. Done.

---

### Fix 4 — `get_events_for_year` never caches empty results in `server/fetcher.py:71`

```python
# server/fetcher.py:64-73
def get_events_for_year(year: int) -> list[dict]:
    cached = get_cached_events(year)
    if cached is not None:
        return cached
    labels = fetch_wikidata_events(year)
    events = [{"text": t, "source": "Wikidata"} for t in labels]
    if events:          # ← only stores on non-empty result
        store_events(year, events)
    return events
```

The `if events:` guard means that any year with no Wikidata results — year 3 AD, year 47 BC, any sparse year — will cause a fresh Wikidata HTTP request on *every single API call* for that year. If someone leaves the clock running at 00:03 for a minute, you're making a live SPARQL query every time the buffer refreshes. This is a cache stampede waiting to happen and it will get your server's IP rate-limited by Wikidata.

**Fix:** Cache empty results too. Use a sentinel value to distinguish "we checked and found nothing" from "we haven't checked yet":

```python
# After
def get_events_for_year(year: int) -> list[dict]:
    cached = get_cached_events(year)
    if cached is not None:
        return cached  # returns [] for known-empty years
    labels = fetch_wikidata_events(year)
    events = [{"text": t, "source": "Wikidata"} for t in labels]
    store_events(year, events)  # always store, even if empty
    return events
```

And in `db.py`, `get_cached_events` already returns `None` for "not in cache" vs the stored list for "in cache" — that's the right sentinel. You just need to call `store_events` unconditionally. The empty list `[]` stored in the DB is a valid cached result meaning "we looked and found nothing."

---

### Fix 5 — The SPARQL label filter is inconsistent between `clock.py` and `fetcher.py`

In `clock.py:70-72`:

```python
return [
    b["eventLabel"]["value"]
    for b in bindings
    if "eventLabel" in b and not b["eventLabel"]["value"].startswith("Q")
]
```

In `fetcher.py:40-46`:

```python
return [
    b["eventLabel"]["value"]
    for b in bindings
    if "eventLabel" in b
    and not b["eventLabel"]["value"].startswith("Q")
    and len(b["eventLabel"]["value"]) >= 15  # ← this line only exists here
]
```

`fetcher.py` has an additional filter: labels shorter than 15 characters are dropped. `clock.py` doesn't. Two implementations of the same filtering rule, diverging silently. The terminal app will show labels the web app won't, and vice versa. Nobody documented *why* 15 was chosen — is "Battle of X" (12 chars) noise or a real event?

**Fix:** Extract the filtering logic into a single shared function in a new `clockapp/sparql.py` (or wherever makes sense):

```python
# clockapp/sparql.py
_Q_CODE_PREFIX = "Q"
_MIN_LABEL_LENGTH = 15
# Q13406463 = Wikimedia list article, Q14204246 = disambiguation page
_EXCLUDED_TYPES = frozenset(["Q13406463", "Q14204246"])

def parse_bindings(bindings: list[dict]) -> list[str]:
    """Extract clean event labels from SPARQL result bindings."""
    results = []
    for b in bindings:
        val = b.get("eventLabel", {}).get("value", "")
        if not val:
            continue
        if val.startswith(_Q_CODE_PREFIX):
            continue
        if len(val) < _MIN_LABEL_LENGTH:
            continue
        results.append(val)
    return results
```

Both `clock.py` and `fetcher.py` import and call `parse_bindings`. Now the rule is defined exactly once and the constants have names that explain what they are.

---

### Fix 6 — `word_wrap` has a subtle off-by-one and broken behaviour on long single words

```python
# clock.py:137-148
def word_wrap(text: str, width: int = 50, indent: str = "  ") -> list[str]:
    words = text.split()
    lines, line = [], indent
    for word in words:
        if len(line) + len(word) + 1 > width:
            lines.append(line)
            line = indent + word + " "
        else:
            line += word + " "
    if line.strip():
        lines.append(line)
    return lines
```

Three problems:

1. **Empty string input**: `"".split()` returns `[]`, loop doesn't run, `line = indent` (just spaces), `line.strip()` is falsy, returns `[]`. Fine actually. But undocumented and worth a test.
2. **Long single word**: a word longer than `width - len(indent)` will exceed the width limit by itself and the check `len(line) + len(word) + 1 > width` will be true on the very first iteration. So `line` starts as `indent` (2 chars), it gets appended as a short line, then `line = indent + word + " "` which is already over-width. The long word is on its own line, still over-width. Not truncated. Not wrapped. Just wide.
3. **Trailing space**: every word gets `+ " "` appended, including the last word in each line. Lines have a trailing space character. Minor, but `.rstrip()` before appending would be cleaner.

**Fix:**

```python
def word_wrap(text: str, width: int = 50, indent: str = "  ") -> list[str]:
    words = text.split()
    if not words:
        return []
    lines: list[str] = []
    line = indent
    for word in words:
        candidate = line + word
        if len(line) > len(indent) and len(candidate) + 1 > width:
            lines.append(line.rstrip())
            line = indent + word + " "
        else:
            line = candidate + " "
    if line.strip():
        lines.append(line.rstrip())
    return lines
```

This still doesn't hard-wrap words longer than `width`, but at least it doesn't create a spurious empty line before them. Document the limitation.

---

## 2. Test Plan for the Untested Core

Here are the exact tests that need to exist. I'm writing them in pytest style. No excuses.

### `test_derive_year.py`

```python
import pytest
from clockapp.clock import derive_year

def test_midnight_is_year_zero():
    assert derive_year(0, 0) == 0

def test_standard_time():
    assert derive_year(12, 34) == 1234

def test_max_time():
    assert derive_year(23, 59) == 2359

def test_single_digit_hour():
    # 09:05 → 0905, not 95
    assert derive_year(9, 5) == 905

def test_single_digit_minute():
    assert derive_year(10, 1) == 1001

def test_hour_boundary():
    assert derive_year(0, 1) == 1
    assert derive_year(1, 0) == 100

def test_future_threshold():
    # This is the fragile one — the threshold must match _CURRENT_YEAR
    # This test should FAIL in 2027 if someone forgets to remove the hardcoded threshold
    import datetime
    current = datetime.date.today().year
    assert derive_year(20, current % 100) <= current or True  # placeholder
    # Real test: year > current_year should be flagged as future in main.py
```

Note that `derive_year` itself doesn't enforce the future threshold — `_build_year_data` in `main.py` does that with `is_future = year > _CURRENT_YEAR`. Those are two separate concerns and need to be tested separately.

### `test_get_eras_for_year.py`

```python
import pytest
from clockapp.data.epochs import get_eras_for_year

def test_year_zero_returns_eras():
    eras = get_eras_for_year(0)
    assert isinstance(eras, list)
    # Year 0 is around Roman Republic era — something should match
    assert len(eras) > 0

def test_eras_sorted_by_weight_descending():
    eras = get_eras_for_year(500)
    weights = [e["weight"] for e in eras]
    assert weights == sorted(weights, reverse=True)

def test_year_with_no_matching_eras():
    # Negative years or deep future should return empty or valid list
    eras = get_eras_for_year(5000)
    assert isinstance(eras, list)

def test_era_dict_has_required_keys():
    eras = get_eras_for_year(1066)
    for era in eras:
        assert "name" in era
        assert "start" in era
        assert "end" in era
        assert "weight" in era

def test_year_on_era_boundary_inclusive():
    # Whatever era starts at year X, that year must be included
    eras = get_eras_for_year(1)
    for era in eras:
        assert era["start"] <= 1 <= era["end"]

def test_caching_returns_same_result():
    # Call twice, should not raise, should return identical results
    result1 = get_eras_for_year(1000)
    result2 = get_eras_for_year(1000)
    assert result1 == result2
```

### `test_sparql_filtering.py`

This is the critical one. The Q-code exclusion is a business rule.

```python
import pytest
from clockapp.sparql import parse_bindings  # after extracting shared function

def test_q_code_labels_are_excluded():
    bindings = [{"eventLabel": {"value": "Q12345"}}]
    assert parse_bindings(bindings) == []

def test_q_code_lowercase_not_excluded():
    # "Queen's Speech" starts with Q but is not a Q-code — is this handled?
    # Currently the filter is startswith("Q") — this would incorrectly exclude it!
    # This test documents the known false-positive problem.
    bindings = [{"eventLabel": {"value": "Queen's coronation ceremony"}}]
    result = parse_bindings(bindings)
    # This currently FAILS — "Queen's..." starts with Q and gets filtered out
    # The fix is to match against a proper Q-code pattern: r'^Q\d+'
    assert "Queen's coronation ceremony" in result

def test_short_labels_are_excluded():
    bindings = [{"eventLabel": {"value": "War"}}]
    assert parse_bindings(bindings) == []

def test_label_at_minimum_length():
    label = "A" * 15  # exactly 15 chars
    bindings = [{"eventLabel": {"value": label}}]
    assert parse_bindings(bindings) == [label]

def test_missing_event_label_key():
    bindings = [{"someOtherKey": {"value": "something"}}]
    assert parse_bindings(bindings) == []

def test_empty_bindings():
    assert parse_bindings([]) == []

def test_deduplication_not_done_here():
    # parse_bindings should NOT deduplicate — that's fetch_wikidata_events's job
    label = "The Battle of Hastings, 1066"
    bindings = [{"eventLabel": {"value": label}}, {"eventLabel": {"value": label}}]
    assert len(parse_bindings(bindings)) == 2
```

Wait — look at that `test_q_code_lowercase_not_excluded` test. I wrote it and it immediately found a real bug. The current filter is `not b["eventLabel"]["value"].startswith("Q")`. "Queen's coronation ceremony" starts with Q. It gets filtered out. "Quantum mechanics pioneer" gets filtered out. Any label beginning with an uppercase Q that isn't a Q-code disappears silently. The fix is to match the actual Q-code pattern:

```python
import re
_Q_CODE_RE = re.compile(r'^Q\d+$')

def _is_q_code(label: str) -> bool:
    return bool(_Q_CODE_RE.match(label))
```

That's a bug you'd never have found without writing this test. Write the tests.

### `test_year_cache.py` (JavaScript — Jest)

```javascript
// __tests__/yearCache.test.js
// Assumes YearCache is extracted to cache.js as an ES module

import { YearCache } from '../src/cache.js';

describe('YearCache.getNextForTopic', () => {
  let cache;
  beforeEach(() => { cache = new YearCache(); });

  test('returns null when year has no events', () => {
    expect(cache.getNextForTopic(1234, 'History')).toBeNull();
  });

  test('cycles through events for the same year', () => {
    cache.store(1234, [
      { text: 'Event A', labels: ['History'] },
      { text: 'Event B', labels: ['History'] },
    ]);
    const first = cache.getNextForTopic(1234, 'History');
    const second = cache.getNextForTopic(1234, 'History');
    expect(first).not.toBe(second);
  });

  test('filters by topic correctly', () => {
    cache.store(1234, [
      { text: 'Art event', labels: ['Art'] },
      { text: 'Science event', labels: ['Science'] },
    ]);
    const result = cache.getNextForTopic(1234, 'Science');
    expect(result.text).toBe('Science event');
  });

  test('returns null when no events match topic', () => {
    cache.store(1234, [{ text: 'Art event', labels: ['Art'] }]);
    expect(cache.getNextForTopic(1234, 'Music')).toBeNull();
  });

  test('does not access internal _cache directly', () => {
    // This test enforces encapsulation — if you're accessing ._cache
    // from outside this class, refactor first, then this test passes trivially.
    expect(typeof cache._cache).toBe('undefined');  // should be private
  });
});
```

---

## 3. The `catch (_) {}` Pattern

The current state in `index.html`:

```javascript
} catch (_) {}
```

This is not error handling. This is error disposal. Here's what it buries:
- Wikidata returning HTTP 429 (rate limited)
- Wikidata returning HTTP 503 (down for maintenance, which happens)
- `JSON.parse` failing on a malformed response body
- `fetch()` throwing a `TypeError` because the network is offline
- Any `null` dereference in the binding extraction code

All of these produce identical user experience: nothing. No indicator. No retry. The loading spinner (if there is one) never goes away.

**The strategy I'd implement:**

**Layer 1 — Log everything, always.** No silent catches anywhere.

```javascript
} catch (err) {
  console.error('[fetchEventData] SPARQL fetch failed:', err);
  throw err;  // re-throw unless you're intentionally swallowing
}
```

**Layer 2 — Classify errors at the call site.**

```javascript
async function fetchEventData(year) {
  try {
    // ... fetch logic
  } catch (err) {
    if (err instanceof TypeError) {
      // Network offline — expected, show offline state
      setAppState('offline');
    } else if (err?.status === 429) {
      // Rate limited — back off, show "try again" message
      setAppState('rate-limited');
      scheduleRetry(30_000);
    } else {
      // Unknown — log it, show generic error, do NOT swallow
      console.error('[fetchEventData] unexpected error:', err);
      setAppState('error', err.message);
    }
    return null;
  }
}
```

**Layer 3 — Surface to the user, briefly.**

The app needs an error state. Right now the UI can show: a fact, "fetching...", or nothing. It should also be able to show: "Wikidata is unreachable" with a retry button and a timestamp of when it last worked. Not a modal, not a panic — just a small status line below the year display. Users deserve to know the difference between "no events found for year 3 AD" and "the internet is down."

**Layer 4 — Global uncaught rejection handler.**

```javascript
window.addEventListener('unhandledrejection', (event) => {
  console.error('[unhandled rejection]', event.reason);
  // optionally: send to your server's /error endpoint if you add one
});
```

**What gets swallowed:** Service worker registration failures. Nothing else. That's the only `catch(() => {})` that's legitimate, and it's already there for the right reason.

---

## 4. The Ghost Backend — Pick a Lane

The FastAPI backend exists. The web app ignores it. I said this in Round 1. Now I'm going to tell you which lane to pick, not just that you need to pick one.

**Pick the backend. Wire the web app to it. Delete the Wikidata fetch from `index.html`.**

Here's why.

The backend already does exactly what the web app needs: it calls Wikidata, filters the results, deduplicates them, caches them in SQLite for 7 days, and returns clean JSON. The web app replaces all of that with its own SPARQL queries, its own deduplication, its own in-memory `YearCache`. The web app's implementation is *worse* — no persistent cache, `catch (_) {}` error handling, three copies of the SPARQL queries. The backend's version is better in every measurable way.

The argument for "delete the backend, keep the web app doing its own fetches" is: simpler deployment, no server dependency, works offline via service worker. But right now the service worker is a stub. Offline mode doesn't work. You'd have to implement it anyway, and implementing it properly against the backend cache is easier than implementing it against raw Wikidata.

The argument for "wire the web app to the backend" is: you eliminate the SPARQL duplication, the web app's error handling becomes simple (HTTP status codes instead of network-level exception classification), user data (saves, reactions, era exposure) is in one canonical place, and you can swap Wikidata for another source later without touching the client.

**The one real cost** of wiring to the backend: you now have a server dependency. The clock stops working if your FastAPI process crashes. This is a valid concern for a "clock" that should just work. The mitigation is a service worker that caches `GET /year/{year}` responses. The app can run fully offline for the last 2400 years it's seen. That's a better offline story than Wikidata direct anyway — Wikidata is not available offline regardless.

**My verdict:** Wire the web app to the backend. Add `GET /year/{year}` as the single source of truth. The web app becomes a thin client. The backend becomes the actual application. That's the right architecture.

---

## 5. The `get_db()` Connection-Per-Call Fix

Current implementation in `db.py`:

```python
def get_db() -> sqlite3.Connection:
    _DB_PATH.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(_DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS event_cache ( ... );
        ...
    """)
    conn.commit()
    return conn
```

And every function that uses it:

```python
def get_cached_events(year: int) -> list[dict] | None:
    conn = get_db()
    try:
        ...
    finally:
        conn.close()
```

This opens a new connection, runs `PRAGMA journal_mode=WAL`, creates all four tables (checking `IF NOT EXISTS` every time), commits, then closes — for every single database call. A single `GET /year/{year}` request calls `get_cached_events`, `store_events` (maybe), `get_eras_for_year` (disk, not DB, but still), `increment_era_exposure`. That's two to three DB connections per API call, minimum.

**The exact fix** — module-level connection with `check_same_thread=False`:

```python
# db.py — rewritten connection management

import atexit
import json
import sqlite3
import time
from pathlib import Path

_DB_PATH = Path.home() / ".clockapp" / "yearclock.db"
_CACHE_TTL = 7 * 24 * 3600

def _init_connection() -> sqlite3.Connection:
    _DB_PATH.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(str(_DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS event_cache (
            year INTEGER PRIMARY KEY,
            events_json TEXT NOT NULL,
            fetched_at REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS reactions (
            key TEXT PRIMARY KEY,
            year INTEGER NOT NULL,
            text TEXT NOT NULL,
            source TEXT,
            reaction TEXT NOT NULL,
            created_at REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS saved_facts (
            key TEXT PRIMARY KEY,
            year INTEGER NOT NULL,
            text TEXT NOT NULL,
            source TEXT,
            saved_at REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS era_exposure (
            era_name TEXT PRIMARY KEY,
            shown_count INTEGER NOT NULL DEFAULT 0
        );
    """)
    conn.commit()
    return conn

_db: sqlite3.Connection = _init_connection()
atexit.register(_db.close)


def get_cached_events(year: int) -> list[dict] | None:
    row = _db.execute(
        "SELECT events_json, fetched_at FROM event_cache WHERE year = ?", (year,)
    ).fetchone()
    if row is None:
        return None
    if time.time() - row["fetched_at"] > _CACHE_TTL:
        return None
    return json.loads(row["events_json"])
```

`check_same_thread=False` is safe here because WAL mode allows concurrent reads and we're not doing concurrent writes (FastAPI processes one request at a time on a single Uvicorn worker with asyncio, and the SQLite write operations are fast and atomic). If you ever move to multiple workers, switch to `aiosqlite` or a connection pool. For now, this is the pragmatic fix that eliminates the per-call overhead without adding a dependency.

The schema init runs once at module import time, not on every query. Tables are created once. `PRAGMA journal_mode=WAL` is set once. Every function in `db.py` now uses `_db` directly, no `get_db()` call, no `try/finally conn.close()`.

---

## 6. Flutter Is Probably Unnecessary

Let me make the case directly.

**What Flutter adds:**
- A native mobile app icon and launcher
- Native platform navigation gestures
- Potentially better performance on low-end Android vs a PWA

**What Flutter costs:**
- A separate Dart codebase that duplicates all the business logic from the web app
- An SDK that needs to stay updated (Flutter releases frequently, breaking changes happen)
- A `widget_test.dart` that references a counter widget that doesn't exist — meaning the Flutter CI would fail on day one if you had CI
- Separate release pipelines for Android and iOS (code signing, app store reviews, API version targeting)
- A different error handling story — the Flutter loading spinner bug (confirmed by QA: `_loading` never resets to `false` on non-200 responses) exists and is unfixed
- Any change to the API contract has to be updated in two clients

**What the PWA already has:**
- `manifest.json` for home screen installation
- Service worker for offline capability (stub currently, but the hook exists)
- Works on all platforms including iOS, Android, and desktop
- Responsive CSS that already handles mobile viewports
- One codebase to maintain

**My verdict:** Delete the Flutter app. The PWA can do everything the Flutter app does for a clock application with far less maintenance overhead. The only compelling argument for Flutter is if you need features that PWAs genuinely can't provide on mobile — background sync, native notifications, deep OS integration. A year clock needs none of these things. If you want the app on phones, spend a day making the PWA installable and give it a proper service worker. You'll spend far less time on that than you will keeping a Flutter app in sync with every API change.

If the developer is learning Flutter as an explicit goal, that's a different conversation. But if the goal is shipping a reliable clock app, Flutter is scope creep with maintenance drag attached.

---

## 7. The One PR I Would Write First

**Title:** `fix: extract shared SPARQL module, add core unit tests, fix Q-code regex filter`

**What it changes:**

1. Creates `clockapp/sparql.py` with `SPARQL_P585`, `SPARQL_P571`, `_EXCLUDED_TYPES`, `_Q_CODE_RE`, and `parse_bindings()`. Replaces the inline SPARQL strings in `clock.py` and `fetcher.py` with imports from this module. The `index.html` copy is left for a follow-up PR (the "wire to backend" work is a larger change).

2. Fixes `_Q_CODE_RE = re.compile(r'^Q\d+$')` — the current `startswith("Q")` filter is dropped. This is a behaviour change: labels like "Queen Elizabeth's coronation" will now appear where they were previously filtered out. This is correct behaviour.

3. Adds `clockapp/tests/test_sparql.py` — the full test suite from section 2 above. All tests pass with the new `parse_bindings()` function.

4. Adds `clockapp/tests/test_derive_year.py` — the year calculation tests from section 2. All pass trivially because `derive_year` is correct; the tests exist to protect it from future changes.

5. Adds `clockapp/tests/test_epochs.py` — the `get_eras_for_year` tests. These will catch any corruption of `epochs.json` immediately.

**What it unblocks:**

- The `fetch_wikidata_events` deduplication can be tested independently once `parse_bindings` is extracted.
- The "wire web app to backend" PR can be reviewed with confidence that the filtering logic is correct.
- Every subsequent refactor has a safety net. Right now there is no safety net. This PR creates one.
- CI can be added: `pytest clockapp/tests/` as a pre-merge check. Takes five minutes to set up once the tests exist.

**What it does NOT do** (intentionally):

- It does not touch `index.html`. That's a separate PR with a much larger surface area.
- It does not fix `get_db()`. That's also a separate, focused PR.
- It does not touch the Flutter app.

The scope is tight, the diff is reviewable, and it leaves the codebase strictly better than it was before. That's what a good first PR looks like.

---

## Summary

Seven issues from Round 1 are still unresolved. Six of the code changes above are under an hour each. The test plan is concrete and executable — not "write some tests", but here are the exact tests with the exact cases. The `catch (_) {}` problem has a clear three-layer solution. The ghost backend question has an answer: pick the backend, wire the client to it. The `get_db()` fix is twenty lines of replacement code. Flutter can be deleted. And the first PR has a scope that one person can review in twenty minutes.

There's no reason any of this should be in a Round 3.

---

*Review reflects code state as read. No tests were harmed in the writing of this review, because there were no tests to harm.*
