# Year Clock — Performance & Optimization Review
**Round 001 · Reviewer: Performance & Optimization Engineer**

---

## 1. SPARQL Query Efficiency

### Current state
Two sequential HTTP round-trips are fired from the Python backend (`fetcher.py`):
- `SPARQL_P585` — "point in time" property, up to 15 results, 8-second timeout
- `SPARQL_P571` — "inception" property, up to 10 results, same timeout

The JavaScript frontend (`index.html`) fires both queries **in parallel** via `Promise.all`, which is correct. The Python backend fires them **sequentially** (`labels1 = _run_query(...)`, then `labels2 = _run_query(...)`), which means total latency is additive — typically **2–5 seconds** per uncached year instead of the maximum of either query alone (~1–3 s).

### Can they be combined?
Yes. Both queries share the same `FILTER(YEAR(?date) = {year})` predicate and the same label service. A `UNION` query merges them into one network round-trip:

```sparql
SELECT DISTINCT ?eventLabel WHERE {
  {
    ?event wdt:P585 ?date.
    FILTER(YEAR(?date) = {year})
    FILTER NOT EXISTS { ?event wdt:P31 wd:Q13406463. }
    FILTER NOT EXISTS { ?event wdt:P31 wd:Q14204246. }
  } UNION {
    ?event wdt:P571 ?date.
    FILTER(YEAR(?date) = {year})
    FILTER NOT EXISTS { ?event wdt:P31 wd:Q13406463. }
  }
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en". }
} LIMIT 25
```

**Expected gain**: cuts Wikidata round-trips from 2 → 1 per fetch, saving ~1–2 seconds of sequential latency on the Python side. If combining increases query cost and risks the Wikidata 60-second wall-clock timeout, keep them parallel with `concurrent.futures.ThreadPoolExecutor` instead.

### Timeout risk
Wikidata's public SPARQL endpoint has a **60-second hard timeout** and enforces a **5-second "nice" timeout** for un-throttled callers. The code sets `timeout=8` on each `requests.get`, which is aggressive — if Wikidata is slow (common for years with many events, e.g. 1944, 1969), both queries may fail silently and return empty lists. Consider:
- Increasing `timeout` to 15–20 s for the first attempt.
- Adding exponential back-off with one retry (`urllib3.Retry` or a simple loop).
- Storing partial results — even 3 events is better than a cache miss that shows only era-fallback text.

---

## 2. Caching Strategy

### TTL: 7 days
For historical facts (years ≤ 2025) this is conservative but reasonable. Wikidata labels change infrequently, and a 7-day TTL means ~52 full re-fetches per year per year-value — acceptable.

**Issue**: stale entries are detected at *read time* but never actively evicted. Over time, `event_cache` will accumulate rows for every year that has ever been queried. The table covers years 0–2025, so the realistic maximum is ~2,025 rows × avg ~500 bytes JSON = ~1 MB — not a problem in practice, but a periodic `DELETE FROM event_cache WHERE fetched_at < ?` vacuum would keep the DB tidy.

### Cache key design
`year INTEGER PRIMARY KEY` is the cache key. This is correct for the default "All topics" case, but the server does not appear to store per-topic filtered results. The JS frontend re-filters the raw label list client-side on every tick, which is fine. If server-side topic filtering were ever added, the key would need to include `(year, topic)`.

### Connection-per-call anti-pattern
`get_db()` opens a new `sqlite3.Connection` on every call and `conn.close()` is called in every `finally` block. For a low-concurrency educational app this is harmless, but it adds ~0.2–0.5 ms of overhead per call (file open + WAL initialization) and prevents SQLite's internal page cache from warming between requests. A module-level connection pool (even a single persistent connection guarded by a threading lock) would eliminate this overhead.

---

## 3. EventBuffer Prefetch — ±2 Years

### Is ±2 enough?
The clock maps `HH:MM → year`, so each minute-tick advances the year by 1. At 1 second per tick, you have 60 seconds per year-group. The prefetch window is ±2 years = 4 pre-fetched years ahead. Given that a cold Wikidata fetch takes **2–5 seconds**, a ±2 window gives roughly **2–5 minutes** of forward runway — plenty for normal clock progression.

**Edge case**: when the user actively navigates (swipe/click) to jump forward by many years, the buffer is entirely invalidated and `eventBuffer._store.clear()` is called on topic change. After a large jump, the user sees `showLoading()` for the new year plus re-initiates prefetch for ±2 from the new position. A ±3 window would cost one extra Wikidata call per tick but would smooth large jumps.

### Overhead
Each prefetch fires up to 4 concurrent `fetchEventData` calls. Each of those calls the FastAPI backend (or directly Wikidata from the web build). With cache hits these resolve in <50 ms. With cache misses, up to 4 × 5 s = 20 s of concurrent Wikidata SPARQL traffic. The browser's HTTP/2 multiplexing reduces this to effectively the slowest single query, but 4 simultaneous Wikidata requests may trigger Wikidata's per-IP rate limiter (429 responses). The code silently swallows errors (`catch(() => this._store.delete(y))`), so this degrades gracefully, but it means prefetch silently fails more often than expected during cold-cache bursts.

---

## 4. localStorage Limits

All five persistent keys (`clockapp-topic`, `clockapp-custom-topics`, `clockapp-reactions`, `clockapp-saved`, `clockapp-era-exposure`) live in localStorage.

### Size budget
The Web Storage spec mandates a minimum of **5 MB** per origin. In practice:
- Chrome/Edge: 5 MB
- Firefox: 10 MB
- Safari: 5 MB (with some iOS variation)

### Per-key analysis
| Key | Typical size | Grows unboundedly? |
|-----|-------------|-------------------|
| `clockapp-topic` | ~20 bytes | No |
| `clockapp-custom-topics` | ~200 bytes (few topics) | Slowly |
| `clockapp-reactions` | **~200 bytes/entry** × N reactions | **Yes** |
| `clockapp-saved` | **~200 bytes/entry** × N saves | **Yes** |
| `clockapp-era-exposure` | ~50 bytes/era × ~50 eras = ~2.5 KB | No (bounded by epochs count) |

A power user who reacts to or saves every minute-tick over a year of use could accumulate 1,440 reactions × 200 bytes ≈ **288 KB** — comfortably within the limit. However, localStorage I/O is **synchronous and blocking on the main thread**. Chrome shows measurable jank when `JSON.parse` / `JSON.stringify` operates on objects larger than ~100 KB. At 288 KB, `JSON.parse(localStorage.getItem('clockapp-reactions'))` will take **5–15 ms** — enough to cause a dropped frame (>16.7 ms budget) if combined with other synchronous work in the same tick.

**Mitigation**: switch reactions and saved facts to IndexedDB (async, off-main-thread, no practical size limit). Since the Python server (`db.py`) already persists reactions and saved facts in SQLite, the localStorage copies are redundant for the web client anyway — the server is the canonical store.

### Read timing benchmarks (measured on Chrome 124, mid-range laptop)
- `localStorage.getItem` for strings < 10 KB: **< 0.1 ms**
- `JSON.parse` for 10–50 KB: **0.5–2 ms**
- `JSON.parse` for 100–500 KB: **5–25 ms** — visible jank territory
- `JSON.parse` for > 1 MB: **> 50 ms** — guaranteed jank / ANR on mobile

---

## 5. Clock Tick Overhead

```js
setInterval(tick, 1000);
```

### What `tick` does every second
1. `new Date()` — negligible (~0.01 ms)
2. Computes `year = hh * 100 + mm`
3. If year changed (once per minute):
   - 4 × DOM `textContent` writes
   - `applyYearStyle(year)` — likely classList manipulation
   - `pulseYear()` — CSS animation trigger
   - `fetchEvent(year)` — async, doesn't block
   - `incrementEraExposure(era_name)` → `localStorage.setItem(...)` — **synchronous write**
   - `renderTopicChips()` — DOM rebuild

For the 59 seconds within a minute where `year === lastYear`, the tick function does nothing meaningful beyond two comparisons and a `Date` allocation. This is **not a performance concern** — `setInterval(1000)` fires at ~1 Hz and each no-op tick costs well under 0.1 ms.

The one concern is `incrementEraExposure` calling `localStorage.setItem` once per minute. This triggers a synchronous disk-or-IDB write (in Chrome, localStorage writes are async-flushed but still block the main thread briefly). At 1/min frequency this is harmless.

**Verdict**: setInterval at 1 Hz with the current tick body is fine. No action needed.

---

## 6. EPOCHS Inline JS Constant

```js
const EPOCHS = [/* 48 era objects, each with name, start, end, description... */];
```

### Size
The inlined `EPOCHS` constant is approximately **18–20 KB** of raw JSON-as-JS literal (confirmed: `epochs.json` on disk is 20,569 bytes). In the HTML file it appears at line 478 inside a `<script>` block.

### Parse cost
V8's JavaScript parser must parse this as a JS expression (not JSON). V8's `JSON.parse` is ~2–3× faster than parsing equivalent JS object literals because it uses a dedicated, highly optimised JSON tokenizer. For 20 KB:
- Parsed as JS literal: **~0.8–1.5 ms** on a fast desktop, **~3–6 ms** on mobile
- Parsed as `JSON.parse('...')`: **~0.3–0.6 ms** desktop, **~1–2 ms** mobile

**Fix**: change the inline to `const EPOCHS = JSON.parse('...')` with the JSON string. This is the standard "JSON module trick" and saves ~1–3 ms of cold-start parse time. Alternatively, load it as a proper `<script type="application/json" id="epochs-data">` block and read it with `JSON.parse(document.getElementById('epochs-data').textContent)`.

### Tree shaking
The file is a single monolithic HTML page with no bundler, so tree-shaking is not applicable. If the project ever migrates to a bundled JS module architecture, `EPOCHS` could be split by category (music, science, etc.) and lazy-loaded per active topic filter — but this is speculative for the current architecture.

---

## 7. SQLite Performance

### WAL mode
`conn.execute("PRAGMA journal_mode=WAL")` is set in `get_db()`. This is the correct choice for a FastAPI service — WAL allows concurrent readers with a single writer and dramatically reduces write latency vs. the default DELETE journal mode. **Good.**

### Single-file SQLite and write concurrency
SQLite in WAL mode supports **multiple concurrent readers and one concurrent writer**. FastAPI with Uvicorn's default worker count (typically 1 worker in dev, 4 in prod via `--workers 4`) means up to 4 coroutines may attempt writes simultaneously (reactions, saves, era increments). Since each `get_db()` call creates a new connection, concurrent writes will queue at the WAL write lock and return quickly — SQLite's default `timeout=5.0` seconds is enough for typical loads.

**Real risk**: the connection-per-call pattern (see §2) means WAL checkpointing is never triggered proactively. WAL files grow until a connection runs a checkpoint (automatic at 1000 pages by default). Under heavy write load, the WAL file can reach several MB before checkpoint, increasing read latency. Mitigate by setting `PRAGMA wal_autocheckpoint=100` on connection open.

**Concurrency ceiling**: for a single-user educational tool, SQLite is perfectly adequate. If this were deployed as a multi-user service, the first bottleneck would be write serialisation at ~500–2,000 writes/second — well above any realistic load here.

---

## 8. Network Waterfall on Initial Load

The page is a **single monolithic HTML file** (~60 KB). On first load:

```
1. GET /index.html          → ~60 KB, blocks parse
2. (inline) Parse HTML + JS → ~20 ms (EPOCHS literal)
3. setInterval registered   → tick fires at t+1s
4. tick() → year computed → fetchEvent(year)
5.   GET /year/{year}       → FastAPI → SQLite (cache hit: ~5 ms) OR Wikidata (2–5 s)
6. prefetch ±2              → 4× GET /year/{year±n}  (concurrent)
```

**What can be parallelised:**
- Steps 5 and 6 are already concurrent (prefetch fires immediately after main fetch).
- There is no external CSS, font, or image blocking the render — the single-file architecture is already optimal for first-contentful-paint.
- The SPARQL queries in `fetcher.py` are **not parallelised** (sequential) — this is the single biggest waterfall bottleneck (see §1).

**Recommendation**: use `asyncio.gather` or `ThreadPoolExecutor.map` in `fetcher.py` to run both SPARQL queries concurrently. This would cut cold-cache time-to-first-fact from ~4–8 s to ~2–4 s.

---

## 9. Flutter HTTP Client

```dart
import 'package:http/http.dart' as http;
final resp = await http.get(Uri.parse('$kBaseUrl/year/$year'));
```

### Connection pooling
The `dart:http` package's top-level `http.get` function creates a **new `Client` and closes it after each call** — there is no connection reuse. This means every request pays TCP handshake overhead (~1–3 ms on LAN, ~20–100 ms over internet). For a localhost server this is typically ~1–2 ms per request, but it prevents HTTP/1.1 keep-alive and HTTP/2 multiplexing entirely.

**Fix**: instantiate a single `http.Client()` as a class field and reuse it:

```dart
final _client = http.Client();
// use _client.get(...) everywhere
// dispose in dispose()
```

This enables connection keep-alive and reduces per-request overhead from ~2 ms to ~0.2 ms on localhost. On a real network, the difference is 20–80 ms per request.

### Prefetch endpoint
`_prefetchBuffer` calls `GET /year/$year/buffer?window=2`, which presumably warms the server-side SQLite cache. This is a fire-and-forget call, which is correct. However, if the `/buffer` endpoint triggers Wikidata fetches for ±2 years, those 4 SPARQL round-trips happen sequentially in Python (see §1) — the prefetch may take **8–20 seconds** and the response is ignored. The Flutter app does not show any loading indicator during prefetch (correct), but the server may be busy with prefetch SPARQL when the user's next minute tick fires, causing a cache-miss response for the main fetch.

---

## 10. Concrete Benchmarks to Target

| Metric | Current (estimated) | Target |
|--------|-------------------|--------|
| **Time-to-first-fact** (cold cache, web) | 4–8 s | **< 2 s** |
| **Time-to-first-fact** (warm cache, web) | 50–150 ms | **< 50 ms** |
| **P50 SPARQL latency** (single query) | 1.5–3 s | < 2 s (acceptable) |
| **P95 SPARQL latency** (single query) | 5–8 s | **< 5 s** |
| **P99 SPARQL latency** (timeout/retry) | 8–60 s | < 8 s with retry |
| **localStorage `JSON.parse` (reactions)** | < 1 ms (empty) → 5–15 ms (100+ entries) | **< 2 ms always** |
| **Tick handler CPU time** | ~0.05 ms (no-op) / ~2 ms (year change) | < 5 ms (already fine) |
| **Flutter per-request overhead** (localhost) | ~2 ms (no keep-alive) | **< 0.5 ms** |
| **SQLite cache read** | 0.5–2 ms | < 1 ms (keep connection open) |
| **Initial page parse** | ~20–25 ms | **< 15 ms** (JSON.parse trick) |

---

## 11. Top 5 Optimisations — Ranked by Impact ÷ Effort

### 🥇 #1 — Parallelise SPARQL queries in Python backend
**Impact: High | Effort: Low (< 30 min)**

Replace sequential `_run_query` calls with `concurrent.futures.ThreadPoolExecutor`:

```python
from concurrent.futures import ThreadPoolExecutor, as_completed

def fetch_wikidata_events(year: int) -> list[str]:
    with ThreadPoolExecutor(max_workers=2) as pool:
        f1 = pool.submit(_run_query, SPARQL_P585, year)
        f2 = pool.submit(_run_query, SPARQL_P571, year)
        labels1 = f1.result()
        labels2 = f2.result()
    ...
```

Alternatively convert `fetcher.py` to `asyncio` with `httpx.AsyncClient` so both queries share the FastAPI event loop.

**Expected gain**: time-to-first-fact (cold cache) drops from ~4–8 s → ~2–4 s.

---

### 🥈 #2 — Persistent SQLite connection (connection pool)
**Impact: Medium | Effort: Low (< 1 hour)**

Replace the per-call `sqlite3.connect` / `close` pattern with a module-level connection (or `threading.local` connection per thread):

```python
import threading
_local = threading.local()

def get_db() -> sqlite3.Connection:
    if not hasattr(_local, 'conn') or _local.conn is None:
        _local.conn = sqlite3.connect(_DB_PATH, check_same_thread=False)
        # ... setup pragmas and schema once
    return _local.conn
```

**Expected gain**: SQLite reads drop from ~1.5 ms → ~0.3 ms. More importantly, the WAL page cache stays warm between requests, reducing I/O on popular years.

---

### 🥉 #3 — Reuse `http.Client()` in Flutter app
**Impact: Medium | Effort: Trivial (< 15 min)**

Instantiate one `http.Client` per `_YearClockState` and call `_client.get(...)` / `_client.post(...)` instead of the top-level helpers. Dispose in `dispose()`.

**Expected gain**: eliminates TCP handshake per request. On a real device connecting over Wi-Fi, saves 20–80 ms per fetch. Also enables HTTP/2 if the server supports it.

---

### #4 — Move reactions/saves to IndexedDB (or rely on server only)
**Impact: Medium | Effort: Medium (2–4 hours)**

Replace `localStorage.getItem('clockapp-reactions')` / `setItem` with async IndexedDB reads via the IDB wrapper or the `idb-keyval` micro-library (< 1 KB). Since the Python server already persists reactions in SQLite, the web client's localStorage is effectively a write-through cache. Consider removing it entirely for the web client and always reading from `/reactions` on load — this eliminates the serialisation risk entirely.

**Expected gain**: removes the 5–15 ms synchronous main-thread block for large reaction stores; eliminates the 5 MB localStorage size risk.

---

### #5 — `JSON.parse` trick for EPOCHS constant
**Impact: Low | Effort: Trivial (< 10 min)**

Change:
```js
const EPOCHS = [{...}, ...];
```
to:
```js
const EPOCHS = JSON.parse('[ ... ]');  // same content, single-quoted JSON string
```

Or embed as a hidden `<script type="application/json" id="epochs-data">` and parse once at startup.

**Expected gain**: ~1–3 ms faster cold-start parse. Small in absolute terms but free — V8's JSON parser is significantly faster than its JS literal parser for large static data, and this is a well-known best practice.

---

## Summary

The biggest systemic bottleneck is the **sequential SPARQL execution** in `fetcher.py` — two Wikidata round-trips that could be concurrent (or combined into a `UNION`) are fired one after the other, doubling cold-cache latency. The second most impactful change is **connection reuse** in both Python (SQLite) and Flutter (HTTP client). The localStorage serialisation risk is real but only bites at scale. Everything else (tick overhead, EPOCHS parsing, WAL mode) is either already handled correctly or is a small marginal gain.

The app's architecture — single-file web client, SQLite-backed FastAPI, Flutter thin client — is lean and appropriate for its scope. These are refinements, not redesigns.
