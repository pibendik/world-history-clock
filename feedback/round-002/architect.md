# Year Clock — Architectural Review
**Round:** 002  
**Reviewer:** Senior Software Architect  
**Scope:** Prescriptive solutions for all Round 1 findings. No new discovery — this round proposes concrete plans.

---

## 1. Fixing the Dual Wikidata Path

Round 1 identified that the web client calls `https://query.wikidata.org/sparql` directly, in parallel to the FastAPI backend doing the same via `fetcher.py`. The fix is straightforward: make the web app a thin consumer of the API.

**The web app should call:**
```
GET http://localhost:8421/api/v1/year/{year}
```

In `index.html`, replace the `fetchEventData()` function body — which today constructs a SPARQL URL and calls `query.wikidata.org` directly — with a single `fetch` call:

```js
async function fetchEventData(year) {
  try {
    const resp = await fetch(`${API_BASE}/api/v1/year/${year}`);
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const data = await resp.json();
    return data.events ?? [];
  } catch (err) {
    console.error("fetchEventData failed:", err);
    showErrorBanner("Could not load events — server unreachable?");
    return [];
  }
}
```

Add `const API_BASE = window.YEARCLOCK_API_BASE ?? "http://localhost:8421"` near the top of the JS block. This single constant is overridable at deploy time without touching source (e.g., set via a `<script>window.YEARCLOCK_API_BASE="https://api.yearclock.example.com"</script>` injected by nginx).

**In `server/main.py`**, no new endpoint is needed — `/year/{year}` already returns `{events, eras, era_display, is_future}`. The only server change needed is removing the era exposure side-effect from a GET (see §2).

The entire SPARQL block in `index.html` (~120 lines of query construction, deduplication, Q-code filtering) can then be deleted. The `EventBuffer` pre-fetch class survives unchanged — it just switches from calling Wikidata to calling the API.

---

## 2. State Synchronisation Strategy

The localStorage-vs-SQLite split is the core architectural flaw. Here is the concrete migration path.

**Target model: server-authoritative, localStorage as write-through cache.**

The web client gets an anonymous session token on first load:
```js
function getSessionToken() {
  let tok = localStorage.getItem("session_token");
  if (!tok) {
    tok = crypto.randomUUID();
    localStorage.setItem("session_token", tok);
  }
  return tok;
}
```

All POST/DELETE requests include `X-Session-Token: <uuid>` as a header. The server scopes reactions and saved facts to that token — a one-column addition to the SQLite schema:

```sql
ALTER TABLE reactions ADD COLUMN session_token TEXT NOT NULL DEFAULT '';
ALTER TABLE saved_facts ADD COLUMN session_token TEXT NOT NULL DEFAULT '';
CREATE INDEX idx_reactions_session ON reactions(session_token);
CREATE INDEX idx_saved_session ON saved_facts(session_token);
```

**Read path (optimistic, eventual consistency):**
1. On load, web client reads its cached state from localStorage (instant).
2. In the background, it calls `GET /api/v1/saved?session=<token>` and `GET /api/v1/reactions?session=<token>`.
3. Server response is merged into localStorage, with server winning on conflict.
4. Flutter uses the same token (stored in `shared_preferences`) and the same merge strategy.

**Migration from localStorage-only state:**
On first load after the upgrade, if `session_token` does not exist yet but `saved_facts` does exist in localStorage, bulk-upload the existing saves:

```js
async function migrateLocalStorageToServer(token) {
  const saved = JSON.parse(localStorage.getItem("saved_facts") ?? "[]");
  for (const fact of saved) {
    await fetch(`${API_BASE}/api/v1/saved`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Session-Token": token },
      body: JSON.stringify(fact),
    });
  }
  localStorage.removeItem("saved_facts_migrated_legacy"); // sentinel
}
```

Run this exactly once per client (guard with `localStorage.getItem("server_migrated_v1")`). This gives zero data loss for existing users.

---

## 3. API Versioning Strategy

Use **URL path versioning**: `/api/v1/...`. This is the right choice at this scale — it is explicit in logs, bookmarkable, and requires no custom header negotiation. Header-based versioning (`Accept: application/vnd.yearclock.v1+json`) is elegant but opaque; query param versioning (`?v=1`) is fragile and pollutes caches.

**In `main.py`**, add a router:

```python
from fastapi import APIRouter
v1 = APIRouter(prefix="/api/v1")

@v1.get("/year/{year}")
def get_year(year: int):
    ...

app.include_router(v1)
# Keep /health at root (no versioning — it's infrastructure, not API)
```

**Versioned endpoint contract for `/api/v1/year/{year}`:**

```
GET /api/v1/year/1550
→ 200 OK
{
  "year": 1550,
  "events": [{"text": "...", "source": "Wikidata"}],
  "eras": [{"name": "Early Modern", ...}],
  "era_display": "Early Modern",
  "is_future": false
}
→ 422 Unprocessable Entity   (year < 0 or year > 2359)
→ 503 Service Unavailable    (Wikidata unreachable and cache cold)
```

Breaking changes to response shape go to `/api/v2/...`. The v1 router stays frozen. This gives Flutter clients time to migrate without forced upgrades.

---

## 4. Fixing `_CURRENT_YEAR = 2025`

**Exact one-line fix** in `server/main.py` (line 30):

```python
# Before:
_CURRENT_YEAR = 2025

# After:
import datetime
_CURRENT_YEAR = datetime.date.today().year
```

This value is re-evaluated on each server startup, which is the correct granularity — no request-time overhead, no stale value in a long-running process that spans a year boundary (a server restart on New Year's Day is a reasonable assumption; if not, use `datetime.date.today().year` inline in `_build_year_data` instead of a module-level constant).

**Why is this in three files?** Because `fetcher.py` also has `_SPARQL_ENDPOINT` and `db.py` likely has `_CACHE_TTL` — each module hardcoded its own constants independently as the code grew organically. The fix in §7 (Pydantic Settings) centralises all of these into one place so this duplication cannot recur.

---

## 5. Buffer Endpoint Redesign

The current implementation is a latency bomb:

```python
# Current: 5 synchronous _build_year_data calls, each potentially 2 Wikidata HTTP calls
{y: _build_year_data(y) for y in range(year - window, year + window + 1)}
```

Worst case with `window=2`: 5 years × 2 queries × 8s timeout = **80 seconds of serial blocking**.

**Proposed design: fire-and-forget with async parallel fetches.**

```python
from fastapi import BackgroundTasks
import asyncio, httpx

@v1.get("/year/{year}/buffer")
async def get_year_buffer(year: int, window: int = 2, background_tasks: BackgroundTasks = None):
    window = min(window, 5)  # hard cap
    years = list(range(year - window, year + window + 1))

    # Return whatever is already cached immediately
    result = {}
    cold_years = []
    for y in years:
        cached = get_cached_events(y)
        if cached is not None:
            result[y] = {"year": y, "events": cached, "cached": True}
        else:
            result[y] = {"year": y, "events": [], "cached": False}
            cold_years.append(y)

    # Kick off parallel fetches for cold years in the background
    if cold_years:
        background_tasks.add_task(_warm_years_parallel, cold_years)

    return result


async def _warm_years_parallel(years: list[int]):
    async with httpx.AsyncClient(timeout=10) as client:
        tasks = [_fetch_and_cache(client, y) for y in years]
        await asyncio.gather(*tasks, return_exceptions=True)
```

This returns in milliseconds for warm cache (the common case) and populates the cache for subsequent requests. The client's `EventBuffer` class already polls adjacent years — it will get fresh data on its next tick. No streaming needed; the existing polling architecture already handles this gracefully.

**Also replace `requests` with `httpx`** in `fetcher.py` for async compatibility. The synchronous `_run_query` can stay for non-async callers but the buffer path should use `httpx.AsyncClient`.

---

## 6. Composite Key Fragility

The current `{year}::{text}` primary key is fragile for three reasons: event text is unbounded in length; it contains colons which collide with the separator; and it must be URL-encoded for the `DELETE /saved/{key}` endpoint, making the client responsible for encoding correctness.

**Proposed schema:**

```sql
-- reactions table (new schema)
CREATE TABLE reactions (
    id          TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(8)))),
    session_token TEXT NOT NULL DEFAULT '',
    year        INTEGER NOT NULL,
    text        TEXT NOT NULL,
    text_hash   TEXT NOT NULL,  -- sha256(text)[:16]
    source      TEXT,
    reaction    TEXT NOT NULL CHECK(reaction IN ('like', 'dislike')),
    created_at  REAL NOT NULL DEFAULT (unixepoch('now')),
    UNIQUE(session_token, text_hash)
);

-- saved_facts table (new schema)
CREATE TABLE saved_facts (
    id          TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(8)))),
    session_token TEXT NOT NULL DEFAULT '',
    year        INTEGER NOT NULL,
    text        TEXT NOT NULL,
    text_hash   TEXT NOT NULL,
    source      TEXT,
    created_at  REAL NOT NULL DEFAULT (unixepoch('now')),
    UNIQUE(session_token, text_hash)
);
```

The `text_hash` column (SHA-256 first 16 hex chars) serves as the deduplication key. The `id` is an 8-byte random hex string — opaque, URL-safe, no encoding required. The `DELETE /saved/{id}` endpoint now takes a short opaque ID, not a 150-character URL-encoded string.

**Migration plan:**
```sql
-- Run once on deploy
BEGIN;
INSERT INTO saved_facts_new (id, year, text, text_hash, source)
SELECT lower(hex(randomblob(8))), year,
       substr(key, instr(key, '::')+2),  -- extract text from composite key
       substr(hex(randomblob(8)), 1, 16), -- placeholder hash; recompute in Python
       source
FROM saved_facts;
DROP TABLE saved_facts;
ALTER TABLE saved_facts_new RENAME TO saved_facts;
COMMIT;
```

In Python, add a `hashlib.sha256(text.encode()).hexdigest()[:16]` helper and use it wherever a key is currently constructed.

---

## 7. Configuration Layer

Add `clockapp/server/config.py`:

```python
from pydantic_settings import BaseSettings
from pydantic import Field
import datetime

class Settings(BaseSettings):
    port: int = Field(8421, env="YEARCLOCK_PORT")
    db_path: str = Field("~/.clockapp/yearclock.db", env="YEARCLOCK_DB_PATH")
    sparql_endpoint: str = Field(
        "https://query.wikidata.org/sparql", env="YEARCLOCK_SPARQL_ENDPOINT"
    )
    sparql_timeout: float = Field(8.0, env="YEARCLOCK_SPARQL_TIMEOUT")
    cache_ttl: int = Field(7 * 24 * 3600, env="YEARCLOCK_CACHE_TTL")
    current_year: int = Field(
        default_factory=lambda: datetime.date.today().year, env="YEARCLOCK_CURRENT_YEAR"
    )
    cors_origins: list[str] = Field(["*"], env="YEARCLOCK_CORS_ORIGINS")

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

settings = Settings()
```

Then in `main.py`, `db.py`, and `fetcher.py`, replace every hardcoded constant with `from clockapp.server.config import settings` and `settings.cache_ttl`, `settings.sparql_endpoint`, etc. This also enables test isolation: `YEARCLOCK_DB_PATH=:memory: pytest` gives a fresh in-memory SQLite database for every test run with zero cleanup code.

---

## 8. gRPC vs REST for Flutter

**At current scale: REST is the correct choice.** There is no evidence of performance problems attributable to the transport layer. The Flutter client makes one request per year navigation — a few hundred bytes of JSON. gRPC would add `protoc`, `.proto` files, a Dart `grpc` dependency, and a TLS requirement, for zero measurable benefit.

**When gRPC becomes worth it:**
- If the Flutter client needs to stream events (server-push as facts arrive) — gRPC server streaming handles this elegantly.
- If there are >50 RPC types and the auto-generated type-safe stubs start to save meaningful developer time vs. manual JSON models.
- If the service is called by multiple language clients (Go, Python, Dart simultaneously) where a shared `.proto` contract is the source of truth.

None of these conditions hold today. Stay on REST. Add OpenAPI schema validation (`response_model=` annotations in FastAPI) to get the type safety benefit of gRPC without the complexity.

---

## 9. Target Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                        Clients                                  │
│                                                                 │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────────┐  │
│  │  Web PWA     │    │  Flutter App │    │  CLI / clock.py  │  │
│  │ (index.html) │    │  (iOS/Android│    │  (terminal)      │  │
│  └──────┬───────┘    └──────┬───────┘    └────────┬─────────┘  │
│         │ HTTP/JSON         │ HTTP/JSON            │ HTTP/JSON  │
└─────────┼───────────────────┼──────────────────────┼───────────┘
          │                   │                      │
          ▼                   ▼                      ▼
┌─────────────────────────────────────────────────────────────────┐
│                     nginx (optional, port 80/443)               │
│         Static file serving (PWA) + reverse proxy to API        │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│              FastAPI Service  (port 8421)                       │
│                                                                 │
│   GET /api/v1/year/{year}   POST /api/v1/reaction               │
│   GET /api/v1/year/{year}/buffer                                │
│   GET /api/v1/saved         POST /api/v1/saved                  │
│   GET /api/v1/eras          DELETE /api/v1/saved/{id}           │
│                                                                 │
│  ┌──────────────┐   ┌────────────────────────────────────────┐  │
│  │  config.py   │   │  fetcher.py  (httpx async)             │  │
│  │  (Settings)  │   │  ─ SPARQL_P585 + SPARQL_P571 parallel  │  │
│  └──────────────┘   └───────────────────┬────────────────────┘  │
│                                         │ cache miss only       │
│  ┌──────────────────────────────────────▼────────────────────┐  │
│  │  SQLite  (~/.clockapp/yearclock.db, WAL mode)              │  │
│  │   events(year, json, fetched_at)    7-day TTL              │  │
│  │   reactions(id, session, year, text_hash, reaction)        │  │
│  │   saved_facts(id, session, year, text_hash, text)          │  │
│  │   era_exposure(era_name, count)                            │  │
│  └──────────────────────────────────────┬────────────────────┘  │
└─────────────────────────────────────────┼─────────────────────-─┘
                                          │ cache miss
                                          ▼
                          ┌───────────────────────────┐
                          │   Wikidata SPARQL endpoint │
                          │   query.wikidata.org       │
                          └───────────────────────────┘

┌──────────────────────────────────────────┐
│  Admin / Cron (optional, future)         │
│  cache_warmer.py --years 1000:2025       │
│  → calls /api/v1/year/{y} sequentially  │
│  → populates SQLite before user traffic │
└──────────────────────────────────────────┘
```

All three clients speak to a single API surface. The web PWA is served as static files by nginx (or directly by FastAPI's `StaticFiles` mount). The Flutter app and CLI use the same JSON contract. No client touches Wikidata directly. The SQLite cache is the only persistent store. A future cache-warmer cron can pre-populate the events table overnight so that cold-cache latency never affects real users.

---

## 10. The Single Most Important Change to Make First

**Wire the web app to the FastAPI backend.**

Everything else in this document — state sync, versioning, async parallelism, better keys — is easier to implement once the web client routes through the API. Right now there are two competing implementations of the same logic. Every bug fix, SPARQL tuning, or caching improvement must be made twice. Every state write from the web client (reactions, saves, era exposure) goes to localStorage and is invisible to SQLite. The server-side cache — the feature that makes the app fast — is bypassed entirely by the web client, which re-fetches from Wikidata on every page load.

The web-to-API change is a **one-afternoon refactor**: replace ~120 lines of SPARQL boilerplate in `index.html` with 15 lines of `fetch()` calls. The `EventBuffer` class stays; it just changes its data source. The server requires no new endpoints. The result: all future changes happen in one place, the web client gets the 7-day cache for free, IP privacy is restored, and the foundation exists to route saved facts and reactions through the API (which unlocks cross-device state sync).

Do this first. Every other improvement in this document builds on it.

---

*End of architectural review. Round 002.*
