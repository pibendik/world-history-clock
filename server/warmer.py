"""Background cache warmer: pre-fetches all 1440 year-slots."""
import asyncio
import datetime
import logging

from clockapp.server.db import get_cached_events, get_all_cached_years
from clockapp.server.fetcher import get_events_for_year
from clockapp.server.scorer import score_events
from clockapp.server.config import settings

logger = logging.getLogger(__name__)


def _all_clock_years() -> list[int]:
    """All valid years derived from HH:MM (00:00=0 to 23:59=2359)."""
    return [hh * 100 + mm for hh in range(24) for mm in range(60)]


def _prioritised_years() -> list[int]:
    """
    Return all 1440 clock years ordered so the most immediately useful ones
    come first. Starts from ~now and wraps around, so after a daytime deploy
    the current and upcoming hours are cached within minutes rather than hours.
    """
    now = datetime.datetime.now(datetime.timezone.utc)
    all_years = _all_clock_years()
    # Find the index closest to the current UTC time
    current = now.hour * 100 + now.minute
    # Binary search isn't needed — just find the first year >= current
    start = next((i for i, y in enumerate(all_years) if y >= current), 0)
    return all_years[start:] + all_years[:start]


async def warm_cache(delay_seconds: float = 5.0) -> None:
    """
    Warm the cache for all 1440 clock years.
    Skips years already cached. Runs at delay_seconds per year.
    Starts from the current UTC time so today's remaining hours are cached first.
    At 5s/year → fills ~1440 uncached years in 2 hours.
    """
    years = _prioritised_years()
    filled = 0
    skipped = 0
    failed = 0
    logger.info(
        "Cache warmer starting: %d years to check (from year %d forward)",
        len(years), years[0],
    )

    for year in years:
        try:
            if get_cached_events(year) is not None:
                skipped += 1
                continue
            loop = asyncio.get_event_loop()
            events = await loop.run_in_executor(None, get_events_for_year, year)
            if events:
                filled += 1
                logger.debug("Warmed year %d: %d events", year, len(events))
            else:
                logger.debug("Year %d: no events (era fallback)", year)
            await asyncio.sleep(delay_seconds)
        except Exception as exc:
            failed += 1
            logger.warning("Warmer failed for year %d: %s", year, exc)
            await asyncio.sleep(delay_seconds)

    logger.info(
        "Cache warm complete: filled=%d skipped=%d failed=%d",
        filled, skipped, failed,
    )


def _seconds_until_next_4am_utc() -> float:
    """Seconds until the next 04:00 UTC."""
    now = datetime.datetime.now(datetime.timezone.utc)
    target = now.replace(hour=4, minute=0, second=0, microsecond=0)
    if target <= now:
        target += datetime.timedelta(days=1)
    return (target - now).total_seconds()


async def rescore_cache() -> None:
    """
    Re-run LLM scoring over all cached entries.
    Called nightly when YEARCLOCK_LLM_SCORING is enabled, so that entries
    stored before scoring was activated get cleaned up on the next 04:00 pass.
    No-op if LLM scoring is disabled or OPENAI_API_KEY is unset.
    """
    if not settings.llm_scoring_enabled:
        return
    entries = get_all_cached_years()
    if not entries:
        return
    logger.info("LLM rescore pass: %d cached years", len(entries))
    rescored = 0
    for year, events in entries:
        try:
            labels = [e["text"] for e in events]
            filtered = score_events(year, labels)
            if len(filtered) < len(labels):
                from clockapp.server.db import store_events
                store_events(year, [{"text": t, "source": "Wikidata"} for t in filtered])
                rescored += 1
        except Exception as exc:
            logger.warning("Rescore failed for year %d: %s", year, exc)
    logger.info("LLM rescore complete: updated %d / %d entries", rescored, len(entries))


async def daily_refresh() -> None:
    """Re-warm stale entries every night at 04:00 UTC, then rescore with LLM if enabled."""
    while True:
        wait = _seconds_until_next_4am_utc()
        logger.info(
            "Daily refresh scheduled in %.0f minutes (at 04:00 UTC)",
            wait / 60,
        )
        await asyncio.sleep(wait)
        logger.info("Daily cache refresh starting")
        await warm_cache(delay_seconds=5.0)
        await rescore_cache()
