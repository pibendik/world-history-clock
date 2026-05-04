"""Background cache warmer: pre-fetches all 1440 year-slots."""
import asyncio
import logging

from clockapp.server.db import get_cached_events
from clockapp.server.fetcher import get_events_for_year

logger = logging.getLogger(__name__)


def _all_clock_years() -> list[int]:
    """All valid years derived from HH:MM (00:00=0 to 23:59=2359)."""
    return [hh * 100 + mm for hh in range(24) for mm in range(60)]


async def warm_cache(delay_seconds: float = 60.0) -> None:
    """
    Warm the cache for all 1440 clock years.
    Runs at delay_seconds per year to avoid hammering Wikidata.
    Skips years already cached.
    """
    years = _all_clock_years()
    filled = 0
    skipped = 0
    failed = 0
    logger.info("Cache warmer starting: %d years to check", len(years))

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


async def daily_refresh(interval_hours: float = 24.0) -> None:
    """Periodically re-warm stale entries (faster pace since most are already cached)."""
    while True:
        await asyncio.sleep(interval_hours * 3600)
        logger.info("Daily cache refresh starting")
        await warm_cache(delay_seconds=5.0)
