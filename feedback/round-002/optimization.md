# Year Clock — Performance & Optimization Review
**Round 002 · Reviewer: Performance & Optimization Engineer**
**Prerequisite reading: `feedback/round-001/optimization.md`**

---

Round 1 identified the issues. This round is prescriptive: every finding below comes with exact code, a numeric target, and a rationale. The nine items are ordered by the ratio of expected gain to implementation effort.

---

## 1. Parallel SPARQL Queries in `fetcher.py`

### The problem (recap)
`fetch_wikidata_events` fires `_run_query(SPARQL_P585, year)` and then — only after that returns — fires `_run_query(SPARQL_P571, year)`. Total cold-cache latency is the **sum** of both queries (~2–5 s each = 4–10 s worst case), not the maximum.

### Before

```python
# fetcher.py — current (sequential)
def fetch_wikidata_events(year: int) -> list[str]:
    """Run both SPARQL queries, deduplicate, and filter boring labels."""
    labels1 = _run_query(SPARQL_P585, year)   # blocks here
    labels2 = _run_query(SPARQL_P571, year)   # only starts after labels1 is done
    seen: set[str] = set()
    combined: list[str] = []
    for label in labels1 + labels2:
        if label not in seen:
            seen.add(label)
            combined.append(label)
    return combined
```

### After — `ThreadPoolExecutor` (minimal change, no new deps)

```python
# fetcher.py — parallel with ThreadPoolExecutor
from concurrent.futures import ThreadPoolExecutor

def fetch_wikidata_events(year: int) -> list[str]:
    """Run both SPARQL queries concurrently, deduplicate, and filter."""
    with ThreadPoolExecutor(max_workers=2) as pool:
        fut1 = pool.submit(_run_query, SPARQL_P585, year)
        fut2 = pool.submit(_run_query, SPARQL_P571, year)
        labels1 = fut1.result()   # both queries run in parallel
        labels2 = fut2.result()   # this merely waits for the slower one

    seen: set[str] = set()
    combined: list[str] = []
    for label in labels1 + labels2:
        if label not in seen:
            seen.add(label)
            combined.append(label)
    return combined
```

**Why `ThreadPoolExecutor` instead of `asyncio`?** `_run_query` uses `requests` (a synchronous, blocking HTTP library). Wrapping it in `asyncio.run_in_executor` would work identically, but `ThreadPoolExecutor` is simpler and avoids mixing sync/async contexts. If `fetcher.py` is ever converted to `httpx.AsyncClient`, use `asyncio.gather` instead.

**Measurable target:**
| Metric | Before | After |
|--------|--------|-------|
| Cold-cache SPARQL time | 4–10 s | 2–5 s (max of both, not sum) |
| Warm-cache response | < 10 ms | < 10 ms (unchanged) |

Measure with `python -m timeit -n 5 "from clockapp.server.fetcher import fetch_wikidata_events; fetch_wikidata_events(1969)"` before and after the change.

---

## 2. Persistent SQLite Connection in `db.py`

### The problem (recap)
Every function in `db.py` calls `get_db()`, which calls `sqlite3.connect(...)`, runs one query, and calls `conn.close()`. This incurs ~0.3–0.8 ms of file-open and WAL-init overhead on every call. The WAL page cache is thrown away between calls, so frequently-read years always cold-read from disk.

### Before

```python
# db.py — current (connection-per-call)
def get_cached_events(year: int) -> list[dict] | None:
    conn = get_db()   # opens a new file handle every time
    try:
        row = conn.execute(...).fetchone()
        ...
    finally:
        conn.close()  # discards WAL page cache
```

### After — `threading.local` persistent connection

```python
# db.py — persistent per-thread connection
import threading

_local = threading.local()

def get_db() -> sqlite3.Connection:
    """Return a cached, per-thread SQLite connection. Creates it on first call."""
    conn: sqlite3.Connection | None = getattr(_local, "conn", None)
    if conn is not None:
        return conn

    _DB_PATH.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(str(_DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA wal_autocheckpoint=100")  # checkpoint every 100 pages
    conn.execute("PRAGMA synchronous=NORMAL")       # safe with WAL; faster writes
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS event_cache ( ... );
        CREATE TABLE IF NOT EXISTS reactions ( ... );
        CREATE TABLE IF NOT EXISTS saved_facts ( ... );
        CREATE TABLE IF NOT EXISTS era_exposure ( ... );
    """)
    conn.commit()

    # Confirm WAL mode is active (PRAGMA returns the mode that was set)
    mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    assert mode == "wal", f"Expected WAL mode, got: {mode}"

    _local.conn = conn
    return conn


# All callers drop the try/finally conn.close() pattern:
def get_cached_events(year: int) -> list[dict] | None:
    conn = get_db()   # reuses the thread-local connection — no open/close
    row = conn.execute(
        "SELECT events_json, fetched_at FROM event_cache WHERE year = ?", (year,)
    ).fetchone()
    if row is None:
        return None
    if time.time() - row["fetched_at"] > _CACHE_TTL:
        return None
    return json.loads(row["events_json"])
```

**Three pragmas explained:**
- `journal_mode=WAL` — already present; confirmed correct.
- `wal_autocheckpoint=100` — checkpoint after 100 dirty pages (~400 KB) instead of the default 1000 pages (~4 MB). Keeps the WAL file small and read performance steady.
- `synchronous=NORMAL` — safe with WAL (no data loss on OS crash; only risk is power failure mid-write, which is acceptable for a cache). Halves fsync calls on every write.

**Measurable target:**
| Metric | Before | After |
|--------|--------|-------|
| SQLite cache read (warm page cache) | 0.5–2 ms | **< 0.3 ms** |
| SQLite write (reaction/save) | 1–3 ms | **< 0.5 ms** |

Measure with Python `timeit`: `timeit.timeit(lambda: get_cached_events(1969), number=1000)`.

---

## 3. Flutter `http.Client` Reuse

### The problem (recap)
`http.get(uri)` (the top-level function) creates a new `Client` instance, makes the request, and immediately closes the client. No TCP keep-alive, no HTTP/2 multiplexing. Every request pays a full TCP handshake.

### Before

```dart
// main.dart — current (new client per request, implicit)
import 'package:http/http.dart' as http;

Future<void> _fetchYear(int year) async {
  final resp = await http.get(Uri.parse('$kBaseUrl/year/$year'));  // new Client each time
  ...
}
```

### After

```dart
// main.dart — reuse a single Client for the widget's lifetime
import 'package:http/http.dart' as http;

class _YearClockState extends State<YearClock> {
  late final http.Client _client;  // single client for the widget's lifetime

  @override
  void initState() {
    super.initState();
    _client = http.Client();       // created once
    // ... rest of init
  }

  @override
  void dispose() {
    _client.close();               // released once, cleanly
    super.dispose();
  }

  Future<void> _fetchYear(int year) async {
    final resp = await _client.get(Uri.parse('$kBaseUrl/year/$year'));  // reuses connection
    ...
  }

  Future<void> _prefetchBuffer(int year) async {
    await _client.get(Uri.parse('$kBaseUrl/year/$year/buffer?window=2'));
  }

  Future<void> _postReaction(int year, String text, String reaction) async {
    await _client.post(
      Uri.parse('$kBaseUrl/reactions'),
      headers: {'Content-Type': 'application/json'},
      body: jsonEncode({'year': year, 'text': text, 'reaction': reaction}),
    );
  }
}
```

**Measurable target:**
| Environment | Before | After |
|-------------|--------|-------|
| Localhost (LAN) | ~2 ms/req overhead | **< 0.3 ms/req** |
| Real Wi-Fi (20 ms RTT) | ~20–40 ms/req overhead | **< 5 ms/req** |
| 4G (80 ms RTT) | ~80–160 ms/req overhead | **< 15 ms/req** |

Measure in Flutter DevTools → Network tab. Compare the "Connection setup" column before and after.

---

## 4. IndexedDB Migration Plan

### Current state
`localStorage` holds `clockapp-reactions` and `clockapp-saved` as synchronous JSON blobs. Today this is harmless — a typical user accumulates fewer than 100 entries, well within the < 10 KB threshold where `JSON.parse` takes < 0.5 ms.

### When to migrate
Adopt IndexedDB when **either** threshold is crossed in practice (monitor via `localStorage.getItem('clockapp-reactions')?.length` in the browser console):

| Key | Migrate when… | Rationale |
|-----|---------------|-----------|
| `clockapp-reactions` | raw JSON string > **50 KB** (~250 entries) | `JSON.parse` exceeds 2 ms, visible in long-task profiler |
| `clockapp-saved` | raw JSON string > **20 KB** (~100 entries) | Same threshold; saved facts are longer strings |

For reference: 500 reactions × ~200 bytes each = ~100 KB → `JSON.parse` takes ~5–10 ms on mobile. That is above the 4 ms frame budget for a 240 Hz display and will cause jank on repeated reads.

### Recommended library: `idb-keyval`

**Why `idb-keyval` over Dexie.js?**
- `idb-keyval` is **< 1 KB** min+gzip — a drop-in async key-value store with the same API shape as localStorage.
- Dexie.js is excellent (~18 KB) but its query DSL is overkill for two flat key-value stores.
- The full `idb` library (~8 KB) is worth it only if you need indices or cursor-based iteration.

```js
// Migration: replace localStorage calls with idb-keyval
// <script src="https://cdn.jsdelivr.net/npm/idb-keyval@6/dist/umd.js"></script>

// BEFORE (synchronous, blocking)
function loadReactions() {
  return JSON.parse(localStorage.getItem('clockapp-reactions') || '{}');
}
function saveReactions(data) {
  localStorage.setItem('clockapp-reactions', JSON.stringify(data));
}

// AFTER (async, non-blocking)
async function loadReactions() {
  return (await idbKeyval.get('clockapp-reactions')) ?? {};
}
async function saveReactions(data) {
  await idbKeyval.set('clockapp-reactions', data);  // no JSON.stringify needed
}
```

**Note:** Since the Python backend already persists reactions in SQLite, the localStorage copy is purely a client-side cache. The cleanest long-term solution is to **remove the localStorage copy entirely** for the web client and always read from `GET /reactions` on startup — this eliminates the serialisation concern, the 5 MB limit, and the state-sync problem identified by the Architect and Security reviewers.

---

## 5. `JSON.parse` Trick for the EPOCHS Constant

### Why V8 parses JSON faster than JS object literals
V8 has two parsers: a full JavaScript parser (handles expressions, closures, prototype chains, computed keys, etc.) and a dedicated JSON parser. The JSON parser is simpler because JSON is a strict subset of JS with no computed keys, no functions, and no trailing commas. V8 can parse JSON with a single-pass tokeniser; the JS parser requires a full AST construction pass. For a 20 KB payload, the difference is typically **2–4× faster** on the JSON path.

### Before

```js
// index.html — current (parsed as JS expression, slow)
const EPOCHS = [
  { name: "Ancient World", start: 0, end: 499,
    description: "From the earliest recorded history..." },
  // ... 47 more objects, ~20 KB total
];
```

### After — Option A: `JSON.parse` inline string

```js
// index.html — parsed as JSON, ~2–4× faster
const EPOCHS = JSON.parse('[{"name":"Ancient World","start":0,"end":499,"description":"From the earliest recorded history..."},...more...]');
```

This is a one-time mechanical transformation: serialise the existing array with `JSON.stringify`, wrap in single quotes, assign to `JSON.parse(...)`.

### After — Option B: `<script type="application/json">` (cleaner)

```html
<!-- index.html — embed as JSON block, invisible to JS parser on load -->
<script type="application/json" id="epochs-data">
[
  {"name": "Ancient World", "start": 0, "end": 499, "description": "..."},
  ...
]
</script>

<script>
// Parsed lazily when the app reads it — not during initial script evaluation
const EPOCHS = JSON.parse(document.getElementById('epochs-data').textContent);
</script>
```

Option B is cleaner because the JSON block is not evaluated at parse time at all — it is treated as an opaque text node by V8 until `JSON.parse` is explicitly called.

**Measurable target:**
- `performance.now()` before and after the EPOCHS assignment on first load.
- Target: EPOCHS initialisation < **0.5 ms** (down from ~1.5 ms on desktop, ~5 ms on mobile).

---

## 6. SPARQL UNION Query — Single Round Trip

If parallelisation (§1) is not enough, or if you want to eliminate one HTTP connection to Wikidata entirely, merge the two queries into a single `UNION`:

```sparql
SELECT DISTINCT ?eventLabel WHERE {
  {
    ?event wdt:P585 ?date.
    FILTER(YEAR(?date) = {year})
    FILTER NOT EXISTS { ?event wdt:P31 wd:Q13406463. }
    FILTER NOT EXISTS { ?event wdt:P31 wd:Q14204246. }
  }
  UNION
  {
    ?event wdt:P571 ?date.
    FILTER(YEAR(?date) = {year})
    FILTER NOT EXISTS { ?event wdt:P31 wd:Q13406463. }
  }
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en". }
}
LIMIT 25
```

The combined limit is 25 (P585 was 15, P571 was 10). Adjust to taste.

**Implementation in `fetcher.py`:**

```python
# fetcher.py — optional UNION replacement for fetch_wikidata_events
SPARQL_UNION = """
SELECT DISTINCT ?eventLabel WHERE {{
  {{
    ?event wdt:P585 ?date.
    FILTER(YEAR(?date) = {year})
    FILTER NOT EXISTS {{ ?event wdt:P31 wd:Q13406463. }}
    FILTER NOT EXISTS {{ ?event wdt:P31 wd:Q14204246. }}
  }}
  UNION
  {{
    ?event wdt:P571 ?date.
    FILTER(YEAR(?date) = {year})
    FILTER NOT EXISTS {{ ?event wdt:P31 wd:Q13406463. }}
  }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }}
}} LIMIT 25
"""

def fetch_wikidata_events(year: int) -> list[str]:
    """Single UNION query replaces two sequential queries."""
    return _run_query(SPARQL_UNION, year)
```

**Trade-off:** A UNION query may take longer on Wikidata's query planner than two smaller independent queries, particularly for years with thousands of events (e.g. 1969, 1944). Test both approaches against a sample of high-event-density years before committing. If the UNION causes timeouts, fall back to the parallel `ThreadPoolExecutor` approach from §1 — two parallel queries are safer than one slow combined query.

**Recommended path:** implement §1 (parallel) first. Add the UNION only after measuring actual SPARQL execution times.

---

## 7. Cache Warming Strategy — Benchmark Targets

The `buffering-strategy.md` recommends a startup warm-up task running at 1 request/minute (Option D + B hybrid). Here are concrete measurable targets for that warm-up:

### Request rate
| Phase | Rate | Rationale |
|-------|------|-----------|
| Startup warm-up (day 0) | **1 req / 60 s** | Matches the clock's own tick rate; Wikidata's fair-use policy discourages bulk scraping |
| Daily stale refresh (day 1+) | **1 req / 5 s** | Only re-fetches entries older than 7 days (typically < 100 entries/day); faster rate is safe at low volume |
| Test / CI environment | **1 req / 0.1 s** | No Wikidata hit in tests — use a local mock server |

### Expected warm-up timeline

```
Year range: 0–2359 = 2,360 slots
At 1 req/60 s: 2,360 / 60 ≈ 39.3 hours to full cache from cold start
At 1 req/5 s (stale refresh): 100 stale entries / 5 s = 8.3 minutes
```

**Day 0 mitigation:** the client-side ±2 buffer (Option A) covers the first user's visible window immediately. The warm-up runs in the background and does not block any API response.

### Instrumentation targets

Add a `/metrics` or `/health` endpoint (or log line) reporting:

```python
# warmup.py — add progress logging
logger.info(
    "Cache warm-up progress: %d/%d slots filled (%.1f%%), est. %d min remaining",
    filled, total, 100 * filled / total, (total - filled) // 1
)
```

**Benchmark targets for the warmer:**
| Metric | Target |
|--------|--------|
| Warm-up completion (full 2360 slots) | **< 40 hours** from cold start |
| Wikidata 429 rate during warm-up | **< 1%** of requests |
| Cache hit rate after 48 hours | **> 99%** |
| Daily refresh duration (100 stale slots) | **< 10 minutes** |
| Per-year warm time (P50) | **< 3 s** (dominated by Wikidata latency) |

Measure with a counter in `warm_cache_gradually`: log `filled`, `skipped` (already cached), and `failed` (Wikidata error) at completion.

---

## 8. Measuring Improvement — Benchmarking Approach

### What to measure

| Layer | Metric | Tool |
|-------|--------|------|
| SPARQL fetch (Python) | Wall time per `fetch_wikidata_events(year)` | `timeit.timeit` or `time.perf_counter` |
| SQLite read | `get_cached_events(year)` latency | `timeit.timeit(number=10000)` |
| SQLite write | `store_events(year, events)` latency | `timeit.timeit(number=1000)` |
| API endpoint (warm cache) | `GET /year/1969` response time | `curl -o /dev/null -s -w "%{time_total}\n" http://localhost:8421/year/1969` |
| API endpoint (cold cache) | Same, after `DELETE FROM event_cache WHERE year=1969` | Same curl |
| Browser waterfall | DOMContentLoaded + first fact displayed | Chrome DevTools → Network → Waterfall |
| Flutter request | Per-request time (with and without `_client` reuse) | Flutter DevTools → Network tab |
| EPOCHS parse | JS parse time inline | `performance.mark / performance.measure` around the EPOCHS assignment |
| localStorage read | `JSON.parse` for large reaction stores | `console.time / console.timeEnd` |

### How to measure (Python backend)

```python
# Quick benchmark script: benchmark.py
import timeit
from clockapp.server.db import get_cached_events, store_events

# Prime the cache with a known year
store_events(1969, [{"text": "Moon landing", "source": "Wikidata"}])

read_time = timeit.timeit(lambda: get_cached_events(1969), number=10_000)
print(f"get_cached_events (10k runs): {read_time*1000:.2f} ms total, "
      f"{read_time/10:.4f} ms avg")
```

Run this before and after the `db.py` connection-reuse change. Target: average drops from ~1.5 ms to < 0.3 ms.

### How to measure (browser)

```js
// Paste in browser console to measure EPOCHS parse time
performance.clearMarks();
performance.mark('epochs-start');
const EPOCHS_TEST = JSON.parse(document.getElementById('epochs-data')?.textContent ?? '[]');
performance.mark('epochs-end');
performance.measure('epochs-parse', 'epochs-start', 'epochs-end');
console.table(performance.getEntriesByName('epochs-parse'));
```

### How to measure (end-to-end waterfall)

1. Open Chrome DevTools → Network → check "Disable cache".
2. Reload the page.
3. In the Waterfall column, look for:
   - The main HTML document parse time (should be < 20 ms after §5).
   - The first `GET /year/{year}` response (should be < 2 s warm cache, < 5 s cold cache).
   - The four prefetch requests — confirm they fire in parallel, not serially.
4. Record baseline numbers, apply each fix, re-measure.

---

## 9. The Single Optimization with Best Impact/Effort

**Verdict: Parallelise the SPARQL queries (§1).**

Here is the case:

**Impact:** The cold-cache time-to-first-fact drops from ~4–10 seconds to ~2–5 seconds — cutting perceived load time roughly in half. This is the single most user-visible latency in the entire system. Every other path (SQLite reads, localStorage parsing, EPOCHS init, Flutter TCP handshake) operates in the sub-millisecond range by comparison.

**Effort:** The change is exactly **seven lines of Python** — add one import, wrap two `_run_query` calls in a `ThreadPoolExecutor(max_workers=2)`, and call `.result()` on each future. No new dependencies (Python 3.2+), no API changes, no frontend changes, no migration, no schema change.

**Risk:** Near zero. `_run_query` is already thread-safe (no shared mutable state). `ThreadPoolExecutor` with `max_workers=2` caps the thread creation cost. If either query fails, `.result()` propagates the exception identically to the current serial path.

**Comparison to alternatives:**

| Change | Impact | Effort | Risk |
|--------|--------|--------|------|
| **Parallel SPARQL (§1)** | **High** (-50% cold latency) | **~7 lines** | Low |
| Persistent SQLite conn (§2) | Medium (-0.5–1.5 ms/call) | ~20 lines | Low |
| Flutter client reuse (§3) | Medium (-20–80 ms/req on Wi-Fi) | ~5 lines | Low |
| UNION query (§6) | High (same as §1 if no timeout) | ~10 lines | Medium (may timeout) |
| IndexedDB (§4) | Low–Medium (future scale) | 2–4 hours | Medium |
| EPOCHS JSON.parse (§5) | Low (~1–3 ms once) | ~5 min | None |

The parallel SPARQL fix is the only change that directly attacks the dominant cost in the system — Wikidata network latency. Everything else is optimising a fast path that is already fast enough. Do §1 first, measure, then work down the list.

---

## Summary — Prescriptive Action Plan

| # | Change | File | LOC delta | Expected gain |
|---|--------|------|-----------|---------------|
| 1 | Parallel SPARQL with `ThreadPoolExecutor` | `server/fetcher.py` | +5 | Cold-cache latency: -50% |
| 2 | Persistent SQLite thread-local connection | `server/db.py` | +15, -20 | DB read: -80%; write: -70% |
| 3 | Flutter `http.Client` reuse | `flutter_app/lib/main.dart` | +5 | Per-request overhead: -90% on real network |
| 4 | EPOCHS via `JSON.parse` | `web/index.html` | 0 (transform) | Cold parse: -60% |
| 5 | SPARQL UNION (optional, test first) | `server/fetcher.py` | +10 | 1 Wikidata RTT saved per cold fetch |
| 6 | IndexedDB for reactions/saves | `web/index.html` | +20 | Eliminates main-thread block at scale |
| 7 | Cache warmer at 1 req/60 s | `server/warmup.py` (new) | +50 | Zero cold starts after 40 h |

**Total effort for items 1–4:** under 90 minutes. Items 5–7 are day-two work.

**Measurement checkpoint:** after items 1 and 2, run `curl -w "%{time_total}" http://localhost:8421/year/1969` with an empty cache. If total < 3 s, the primary goal is achieved.
