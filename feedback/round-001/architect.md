# Year Clock — Architectural Review
**Round:** 001  
**Reviewer:** Senior Software Architect  
**Files reviewed:** `server/main.py`, `server/db.py`, `server/fetcher.py`, `web/index.html` (key sections)

---

## 1. Overall Architecture Assessment

The overall approach is reasonable for the use case. A clock-as-metaphor for historical browsing is a creative, low-write, high-read application: most traffic is "give me events for year Y" and the data is effectively immutable once fetched from Wikidata. That maps naturally onto a cache-heavy, thin-backend design.

The stack choices (FastAPI + SQLite + vanilla JS PWA) are appropriate for a personal or small-team product. They minimise operational complexity — no database server to manage, no build pipeline, no authentication layer. The 7-day TTL cache for Wikidata results is sensible; historical facts do not change often.

However, the architecture has grown organically and shows signs of **two competing design philosophies** pulling against each other: the web client is essentially a standalone PWA that talks directly to Wikidata, while the Flutter client relies on the FastAPI backend as its exclusive data gateway. This split is the single largest source of architectural risk.

---

## 2. Service Boundaries

The split between client-side and backend logic is inconsistent and will cause maintenance debt:

- The **web client** (`index.html`) contains a full SPARQL engine: it constructs Wikidata queries, calls `https://query.wikidata.org/sparql` directly, parses results, deduplicates, and filters Q-codes — identical logic to `fetcher.py`.
- The **FastAPI backend** re-implements the same query, dedup, and filter pipeline independently.
- **All user state** (reactions, saved facts, era exposure) exists in both `localStorage` *and* the backend SQLite database, with no synchronisation mechanism.

This means a user who switches between the web client and the Flutter client will see completely different saved facts and reactions. There is no concept of identity or session continuity across surfaces.

**Recommendation:** The web client should be a consumer of the FastAPI backend, not a parallel SPARQL client. Move all Wikidata interaction behind the API. This eliminates the duplicate logic, makes the SPARQL queries easier to tune in one place, and sets up a coherent state model.

---

## 3. Data Layer Concerns

SQLite with WAL mode is a solid choice at this scale. Using `~/.clockapp/yearclock.db` is fine for a local-first or single-server deployment.

**When SQLite becomes a problem:**
- **Concurrent writes under load.** WAL mode allows one writer at a time. Under moderate concurrent API traffic (tens of simultaneous write requests), you will see `SQLITE_BUSY` errors. The current code does not handle retries.
- **New connection per operation.** `get_db()` is called and `conn.close()` is called inside every single function. This is correct for correctness but expensive for throughput. A connection pool (even a simple module-level singleton with a threading lock) would be materially faster.
- **Schema migrations.** `CREATE TABLE IF NOT EXISTS` in `get_db()` is an anti-pattern for production. There is no migration history, no version tracking, and no path to alter columns. If a column needs to be added, it must be done manually on every deployment. Consider `alembic` or at minimum a simple version table.
- **The `key` field is `f"{year}::{text}"`** for both reactions and saved facts. Event text from Wikidata can be 100+ characters and contain special characters. This is fragile as a primary key. A content hash (e.g., `sha256(text)[:12]`) would be more robust and compact.

---

## 4. API Contract

The 9 endpoints are functional but have several design issues:

| Issue | Detail |
|---|---|
| **No versioning** | All routes are at `/` root. A future breaking change has no migration path. Prefix with `/api/v1/`. |
| **`/year/{year}/buffer` is a performance footgun** | With `window=2`, this calls `_build_year_data()` 5 times synchronously, each potentially triggering two sequential Wikidata HTTP calls (16 external requests in the worst case, 128-second timeout exposure). |
| **`_build_year_data` has a side effect** | Calling `GET /year/{year}` increments `era_exposure` as a side effect of a read endpoint. This violates HTTP semantics — GET must be idempotent. A `POST /era-view` event or background task would be cleaner. |
| **`DELETE /saved/{key}`** | The key is `{year}::{text}`, which must be URL-encoded by the client. This is fragile. Consider a surrogate integer or UUID primary key. |
| **No pagination** | `GET /reactions` and `GET /saved` return all rows with no limit. These will grow unboundedly. |
| **No 404 on missing saved key** | `remove_saved` silently succeeds even if the key does not exist. The DELETE endpoint should return 404 in that case. |

---

## 5. Cross-Platform Strategy

This is the most significant architectural inconsistency:

- **Web** → talks to Wikidata directly via SPARQL from the browser.
- **Flutter** → talks to FastAPI, which talks to Wikidata.
- **Terminal apps** (`clock.py`, `clock_rich.py`) → presumably call fetcher or Wikidata directly.

Three different data paths for the same conceptual operation ("get events for year Y") means that query changes, rate limiting, or Wikidata API changes must be fixed in multiple places. It also means the web client bypasses the SQLite event cache entirely — every page load re-fetches from Wikidata.

This is a problem today, not just at scale. The web client's `EventBuffer` client-side cache is a workaround for the absence of a shared backend cache. If the backend were the single Wikidata gateway for all clients, all platforms would benefit from the 7-day server-side cache automatically.

---

## 6. Coupling: epochs.json / epochs.py

`epochs.json` is embedded as a JS constant in `index.html` (line 478) *and* exists as `clockapp/data/epochs.py` used by the backend. These are two separate sources of truth with no automated sync check.

Drift is inevitable: if an epoch boundary is corrected in `epochs.py`, the web client continues using the stale embedded version until someone manually re-inlines the JSON. Conversely, edits made by updating the JS constant won't propagate back.

**Recommendation:** Expose epoch data through the API (a `GET /api/v1/eras` endpoint already exists via `/eras` — extend it to include full metadata). The web client should fetch epochs from the API on first load and cache in `localStorage` with a reasonable TTL. This makes `epochs.json` the single canonical source.

---

## 7. Caching Layers

There are currently three caching layers:
1. **Server SQLite** — 7-day TTL for Wikidata events.
2. **`EventBuffer`** (client-side JS object) — in-memory ring buffer, prefetches ±2 years.
3. **`localStorage`** — persists reactions, saved facts, era exposure, topics between sessions.

These are **complementary in intent but redundant in coverage** for the web client, because the web client never uses the server cache at all — it goes directly to Wikidata. So layers 1 and 2+3 serve different clients.

If the web client is moved behind the API (see §5), layer 2 becomes a pure performance optimisation (warm cache for adjacent years), and layer 1 becomes the shared durable cache. This is a clean, complementary model. Currently it is just redundant complexity.

---

## 8. Scalability Path

**From 1 user to 1000:**

| Component | Breaks at | Reason |
|---|---|---|
| SQLite write path | ~20 concurrent writers | WAL allows one writer; reactions/saves will queue or error |
| `/year/{year}/buffer` | ~5 concurrent users | Worst case: 5 users × 16 Wikidata requests = 80 open HTTP connections, 8s timeout × 16 = 128s total exposure per user |
| Wikidata rate limits | ~50 req/min | Wikidata enforces rate limits; no backoff or retry logic exists |
| `localStorage` state | Cross-device users | State is device-local; no sync possible |
| Memory | Not an issue | FastAPI is stateless between requests |

The first thing to break will be the `/year/{year}/buffer` endpoint under any meaningful concurrent load, followed by Wikidata rate-limit errors with no graceful degradation. Adding `asyncio` + `httpx` for the Wikidata fetches and a proper async SQLite layer (e.g. `aiosqlite`) would buy significant headroom before needing to replace SQLite.

---

## 9. Event Sourcing / State (Reactions, Saved Facts, Era Exposure)

The current model stores **current state** (latest reaction, saved fact list, era exposure counts) in SQLite. This is pragmatic and fine for a personal or small-group app.

However, there are two concerns:

1. **No user identity.** All reactions and saved facts are global. Two users sharing a server instance would see each other's data. This will be a problem the moment a second person uses the service. Even a simple anonymous session token (UUID in cookie) would scope state to a device.

2. **Era exposure is split.** The web client tracks exposure in `localStorage`; the backend tracks it in `era_exposure`. These are never reconciled. The `/eras` endpoint returns the backend counter, which is only incremented by Flutter/API clients — the web client's exposure is invisible to the backend.

An event-sourced approach (append `{era, timestamp, client_id}` rows, derive counts from those) would give richer analytics (e.g., exposure over time) at minimal extra cost. Not essential now, but worth the small schema investment.

---

## 10. Backend Service Lifecycle (Auth, CORS)

Wildcard CORS (`allow_origins=["*"]`) and no authentication are acceptable for a local-first personal tool. However, the risk surface is:

- Any page on any origin can call the API and write reactions/saved facts, including forged POST requests from malicious sites (CSRF is not a concern for non-cookie auth, but with wildcard CORS any JS can POST to the API without restriction).
- If the backend is ever exposed on a public IP (e.g., accessed by the Flutter app from a phone), it is a completely open write endpoint.

**When this needs to change:** The moment the service is reachable from outside localhost. A minimal improvement is to restrict `allow_origins` to the known web client origin and add a simple static API key header for the Flutter client. Full auth (OAuth, JWT) is overkill at this stage.

---

## 11. Configuration Management

Several values are hardcoded that should be configurable:

- `_CURRENT_YEAR = 2025` in `main.py` — should be `datetime.date.today().year`.
- `_CACHE_TTL = 7 * 24 * 3600` in `db.py` — reasonable default but not overridable.
- `_SPARQL_ENDPOINT = "https://query.wikidata.org/sparql"` in `fetcher.py` — hardcoded makes it impossible to run against a local Wikidata mirror or test mock.
- `timeout=8` in `_run_query` — not configurable.
- `DB_PATH` is hardcoded to `~/.clockapp/yearclock.db` — prevents running multiple instances or CI test isolation.

A single `config.py` with `pydantic-settings` reading from environment variables (with sensible defaults) would address all of these in ~20 lines and make the service properly 12-factor.

---

## 12. Top 3 Architectural Strengths

1. **Coherent caching strategy.** The SQLite 7-day TTL cache for Wikidata events is exactly right for this data's characteristics: immutable historical facts, slow-changing source, latency-sensitive read path. The design correctly avoids re-fetching on every request.

2. **Clean separation of concerns in the backend.** `fetcher.py`, `db.py`, and `main.py` have clear responsibilities. The layering (API → business logic → cache → external fetch) is textbook and easy to test in isolation. `fetcher.py` is independently testable without standing up the full API.

3. **Right-sized technology choices.** FastAPI + SQLite + vanilla JS PWA is an excellent fit for a personal/hobbyist product. No Kubernetes, no message queues, no ORM — the complexity budget is spent on the product, not the infrastructure. This is a conscious and correct architectural decision for the current scale.

---

## 13. Top 5 Architectural Concerns

### ① Dual SPARQL paths (web + backend) with no shared state
**Impact:** High — bugs/changes must be fixed twice; web client bypasses the server cache entirely.  
**Suggestion:** Route all Wikidata traffic through the API. The web client fetches from `GET /api/v1/year/{year}` instead of calling Wikidata directly. This is a one-afternoon refactor with outsized long-term benefit.

### ② State duplication across localStorage and SQLite with no sync
**Impact:** High — reactions and saved facts created in the web app are invisible to Flutter and vice versa; there is no canonical user state.  
**Suggestion:** Adopt the API as the state authority. Web client POSTs reactions to the API; reads saved facts from the API. LocalStorage becomes a write-through cache, not the source of truth. Requires adding a session token (anonymous UUID) so state can be scoped.

### ③ `/year/{year}/buffer` makes N×2 synchronous Wikidata calls
**Impact:** Medium-High — a single request can block for over a minute under cold-cache conditions.  
**Suggestion:** Make Wikidata fetches async (`asyncio` + `httpx`). Alternatively, make the buffer endpoint fire-and-forget (return immediately with whatever is cached; kick off background prefetch tasks). FastAPI's `BackgroundTasks` makes this trivial.

### ④ No API versioning and fragile key design
**Impact:** Medium — any breaking change to the API or key format requires coordinated client updates with no rollback path.  
**Suggestion:** Prefix all routes with `/api/v1/`. Use UUID or content-hash primary keys for reactions and saved facts instead of `{year}::{text}` composite strings.

### ⑤ _CURRENT_YEAR is a hardcoded constant
**Impact:** Low-Medium — on January 1st 2026, the app will silently return no events for 2026 (treated as future) until someone edits and redeploys `main.py`.  
**Suggestion:** Replace with `datetime.date.today().year`. This is a one-line fix that prevents a real bug.

---

*End of architectural review. Round 001.*
