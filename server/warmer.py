"""Background cache warmer: pre-fetches all 1440 year-slots."""
import asyncio
import datetime
import logging

from clockapp.server.db import get_cached_events
from clockapp.server.fetcher import get_events_for_year

logger = logging.getLogger(__name__)


def _all_clock_years() -> list[int]:
    """All valid years derived from HH:MM (00:00=0 to 23:59=2359)."""
    return [hh * 100 + mm for hh in range(24) for mm in range(60)]


async def warm_cache(delay_seconds: float = 5.0) -> None:
    """
    Warm the cache for all 1440 clock years.
    Skips years already cached. Runs at delay_seconds per year.
    At 5s/year → fills ~1440 uncached years in 2 hours.
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


def _seconds_until_next_4am_utc() -> float:
    """Seconds until the next 04:00 UTC."""
    now = datetime.datetime.now(datetime.timezone.utc)
    target = now.replace(hour=4, minute=0, second=0, microsecond=0)
    if target <= now:
        target += datetime.timedelta(days=1)
    return (target - now).total_seconds()


async def daily_refresh() -> None:
    """Re-warm stale entries every night at 04:00 UTC."""
    while True:
        wait = _seconds_until_next_4am_utc()
        logger.info(
            "Daily refresh scheduled in %.0f minutes (at 04:00 UTC)",
            wait / 60,
        )
        await asyncio.sleep(wait)
        logger.info("Daily cache refresh starting")
        await warm_cache(delay_seconds=5.0)
