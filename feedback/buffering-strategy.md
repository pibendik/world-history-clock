# Buffering / Prefetch Strategy for clockapp

**Status:** Draft  
**Author:** Copilot  
**Date:** 2025-07-14

---

## Problem Statement

The clockapp maps HH:MM military time directly to a year (e.g. 15:50 → 1550). Every minute the clock ticks, a new year is needed — meaning a fresh set of historical events must be available. Events are fetched from the Wikidata SPARQL endpoint, which can take **1–3 seconds** under normal load (and occasionally times out entirely).

Without a prefetch/buffering strategy, every minute-boundary triggers a cold fetch, and the user sees a loading spinner instead of an instant fact. Over the course of a day there are **1,440 unique year-slots** (00:00–23:59 → years 0–2359). Warming all of them in advance is tractable, but naive approaches risk hitting Wikidata rate limits or wasting compute on years the user will never reach.

---

## Options Analysis

### Option A: Client-side Prefetch (Current)

The browser's `EventBuffer` class proactively fetches events for the **current year ± 2** — giving a 2-minute lookahead window.

**How it works:**
- On each minute-tick, JS checks which years ±2 are missing from the in-memory buffer.
- Missing years are fetched from the FastAPI backend (`GET /year/{year}`), which in turn hits Wikidata (or returns a cached SQLite result).
- The `/year/{year}/buffer` endpoint can return ±2 years in a single round-trip.

**Pros:**
- Zero server-side scheduling complexity.
- Naturally follows the user's actual position in time — no wasted fetches for years the user never reaches.
- Works out of the box for a single-user deployment.

**Cons:**
- Cold start on first page load: the first minute is always a spinner if the SQLite cache is empty.
- Browser tab must remain open and active; a backgrounded tab may be throttled by the browser.
- ±2 minute lookahead is small — a slow Wikidata response or brief network outage can still cause a visible delay.
- Does not help a second user: the server-side SQLite cache is only warmed for years the first user visited.

**Scaling limit:** Works well for a single user. For concurrent users visiting different time-zones or fast-forwarding, many simultaneous cold fetches can saturate the Wikidata connection.

---

### Option B: Server Cron Job / Background Worker

A periodic job runs **once daily** (e.g. at 03:00 local time) and iterates over all 1,440 year-slots, fetching events for any cache entry that is missing or older than the 7-day TTL.

**How it works:**
- A shell `cron` entry or in-process scheduler triggers the warm-up.
- The worker iterates `year in range(0, 2360)` and calls the same internal fetch logic as the API endpoint.
- Results are written to the SQLite cache with a fresh timestamp.
- Spread over time to avoid bursting: 1,440 requests / 24 hours ≈ 1 request/minute.

**Scheduling options:**

| Tool | Complexity | Best for |
|------|-----------|---------|
| `cron` | Low | Simple, OS-managed, single server |
| `APScheduler` | Medium | Python in-process, no extra infra |
| `Celery` + Redis | High | Multi-worker, multi-user SaaS |

**Pros:**
- After the daily warm-up completes, **zero cold starts** for any user on any minute.
- Fully server-side — browser tab state is irrelevant.
- Simple to reason about: one job, one schedule.

**Cons:**
- 1,440 SPARQL requests per day. Wikidata's fair-use policy requests a User-Agent header and discourages bulk scraping without rate limiting.
- A 24-hour spread means the first cycle takes a full day to complete — users still see cold starts on day 0.
- Stale data: if a notable event is added to Wikidata mid-week, it won't appear until the next daily run touches that year's TTL.

---

### Option C: Lazy Fill with Background Queue

On every incoming request for year `Y`, the server adds years `Y-5` through `Y+5` (or any configurable window) to an async background queue. A worker drains the queue at a controlled rate.

**How it works:**
- FastAPI endpoint handles the immediate request normally (cache hit → return; cache miss → fetch, cache, return).
- As a side-effect, it enqueues nearby years for background fetching (skip if already cached and fresh).
- An `asyncio` task or `APScheduler` interval job drains the queue at, say, 2 req/s.

**Pros:**
- Demand-driven: only fetches years users actually approach.
- Lookahead window is configurable without any client changes.
- No burst of 1,440 requests — load is spread organically.

**Cons:**
- More complex state management: deduplicating the queue, handling failures, tracking in-flight requests.
- Does not help with the very first user of the day (cache still cold at startup).
- Queue can grow unbounded if the app is used heavily across many years simultaneously.

---

### Option D: Startup Warm-Up

When the FastAPI server starts, it immediately begins a background task that iterates all 1,440 year-slots and fills the SQLite cache — paced at **1 request per minute**.

**Why 1 req/min?**
- The clock itself ticks once per minute, so demand naturally arrives at 1 year/minute.
- Pacing the warm-up at the same rate avoids hammering Wikidata while still completing a full warm cycle in exactly 24 hours.
- After 24 hours the cache is fully warm, and subsequent startups find the cache already populated.

**Pros:**
- Self-healing: every server restart begins a fresh warm-up pass.
- Natural Wikidata pacing — matches the rhythm of the application itself.
- No external scheduler required; purely in-process with `asyncio`.

**Cons:**
- Full warm-up takes 24 hours on first run — not a solution for immediate cold-start elimination on day 0.
- If the server restarts frequently (e.g. during development), the warm-up restarts from the beginning each time.
- Overlaps with the daily cron if both are implemented; needs deduplication logic.

---

## Recommendation: Option D + Option B Hybrid

For a production deployment that starts clean and stays warm, combine both approaches:

1. **On server startup (Option D):** kick off a background `asyncio` task that walks all 1,440 years at 1 req/min. This fills the cache within 24 hours without rate-limit risk.

2. **Daily cron (Option B):** a scheduled job (APScheduler, running in-process) re-fetches any cache entry older than 7 days. This keeps data fresh without requiring a full restart.

3. **Client-side ±2 buffer (Option A):** retain the existing `EventBuffer` in the browser. The server cache is the backstop; the client buffer ensures instant UI response for the currently-visible minute-window even during the warm-up phase.

This hybrid gives:
- **Day 0:** client buffer handles ±2 minutes, all others may have cold starts (acceptable — the cache is filling).
- **Day 1+:** virtually zero cold starts; daily refresh keeps data fresh.
- **No external infrastructure** for a single-user deployment.

---

## Implementation Sketch

```python
# backend/warmup.py
import asyncio
import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from .cache import get_cached_events, fetch_and_cache_events  # existing helpers

logger = logging.getLogger(__name__)

ALL_YEARS = list(range(0, 2360))  # 00:00 → 0, 23:59 → 2359


async def warm_cache_gradually(years: list[int], delay_seconds: float = 60.0):
    """Walk all year-slots at 1 req/min, skipping already-cached entries."""
    for year in years:
        if get_cached_events(year) is not None:
            logger.debug("Cache hit for year %d, skipping", year)
        else:
            logger.info("Warming cache for year %d", year)
            try:
                await fetch_and_cache_events(year)
            except Exception:
                logger.exception("Failed to warm year %d", year)
        await asyncio.sleep(delay_seconds)


async def refresh_stale_entries():
    """Re-fetch any entry older than 7 days (called daily by APScheduler)."""
    stale_years = get_stale_years(max_age_days=7)  # query SQLite for old rows
    logger.info("Daily refresh: %d stale year-slots to refresh", len(stale_years))
    for year in stale_years:
        try:
            await fetch_and_cache_events(year)
        except Exception:
            logger.exception("Failed to refresh year %d", year)
        await asyncio.sleep(5)  # gentler pace for refresh vs. initial warm-up


# backend/main.py  (FastAPI lifespan)
from contextlib import asynccontextmanager
from fastapi import FastAPI
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from .warmup import warm_cache_gradually, refresh_stale_entries, ALL_YEARS

scheduler = AsyncIOScheduler()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Start gradual warm-up in background (1 req/min, non-blocking)
    asyncio.create_task(warm_cache_gradually(ALL_YEARS, delay_seconds=60.0))

    # Schedule daily stale-entry refresh at 03:00
    scheduler.add_job(refresh_stale_entries, "cron", hour=3, minute=0)
    scheduler.start()

    yield  # app is running

    scheduler.shutdown(wait=False)


app = FastAPI(lifespan=lifespan)
```

Key points:
- `warm_cache_gradually` is a fire-and-forget `asyncio.Task` — it doesn't block startup.
- `AsyncIOScheduler` from APScheduler runs inside the same event loop as FastAPI; no threads needed.
- Both functions reuse the existing `fetch_and_cache_events` helper, so cache write logic isn't duplicated.
- The `delay_seconds=60.0` parameter makes it easy to speed up warm-up in tests (`delay_seconds=0.1`).

---

## Scaling Considerations

### Single user (current)
- SQLite + in-process APScheduler is sufficient.
- The SQLite cache file can be placed on a fast local SSD; WAL mode (`PRAGMA journal_mode=WAL`) prevents read/write contention between the API and the warm-up task.

### Multi-user SaaS
- **Cache:** Replace SQLite with **Redis** (TTL-native, shared across workers) or **PostgreSQL** with a `fetched_at` column.
- **Worker:** Move warm-up and refresh to a **Celery** worker process. This decouples fetch load from API latency.
- **Multiple API instances:** With Redis, all API instances share the same cache — no duplicated fetches across pods.

### CDN / Edge Caching (public deployment)
- Add `Cache-Control: public, max-age=3600` to `GET /year/{year}` responses.
- Historical facts change rarely; a 1-hour CDN TTL eliminates origin hits for popular years.
- Combine with `ETag` / `Last-Modified` for conditional requests to avoid stale data after a Wikidata edit.
- At the extreme, pre-generate all 1,440 year responses as static JSON files and serve from a CDN bucket — 0 ms latency, no backend involved.

---

## Summary

| Option | Cold-start risk | Wikidata load | Complexity | Recommended? |
|--------|----------------|---------------|------------|--------------|
| A: Client prefetch | Medium (±2 min only) | Low (demand-driven) | Low | ✅ Keep as UI layer |
| B: Daily cron | Low (after day 1) | Medium (1440/day) | Low–Medium | ✅ For daily refresh |
| C: Lazy queue | Medium | Low–Medium | Medium | ⚠️ Optional enhancement |
| D: Startup warm-up | Low (after 24h) | Low (1/min) | Low | ✅ Primary strategy |

**Bottom line:** implement Option D (startup warm-up) + Option B (daily APScheduler refresh) + keep Option A (client buffer). This covers the full lifecycle with minimal complexity and no external infrastructure requirements for the current single-user deployment.
