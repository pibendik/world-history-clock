import asyncio
import datetime
import os
import sys
import zoneinfo
from contextlib import asynccontextmanager

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from fastapi import APIRouter, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from clockapp.data.epochs import format_era_display, get_context_for_year, get_eras_for_year, get_future_events_for_year
from clockapp.server.db import (
    get_era_exposure,
    get_reactions,
    get_saved,
    increment_era_exposure,
    remove_saved,
    save_fact,
    set_reaction,
)
from clockapp.server.config import settings
from clockapp.server.db import get_db
from clockapp.server.fetcher import get_events_for_year
from clockapp.server.warmer import daily_refresh, warm_cache


@asynccontextmanager
async def lifespan(app: FastAPI):
    asyncio.create_task(warm_cache(delay_seconds=5.0))
    asyncio.create_task(daily_refresh())
    yield


app = FastAPI(title="YearClock API", version="1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Pydantic models ────────────────────────────────────────────────────────────

class ReactionBody(BaseModel):
    year: int
    text: str
    source: str | None = None
    reaction: str  # 'like' or 'dislike'


class SaveBody(BaseModel):
    year: int
    text: str
    source: str | None = None


# ── Helpers ────────────────────────────────────────────────────────────────────

def _build_year_data(year: int) -> dict:
    is_future = year > settings.current_year
    events = [] if is_future else get_events_for_year(year)
    future_events = get_future_events_for_year(year) if is_future else []
    eras = get_eras_for_year(year)
    era_display = format_era_display(year)
    context = get_context_for_year(year)

    if eras:
        increment_era_exposure(eras[0]["name"])

    return {
        "year": year,
        "events": events,
        "future_events": future_events,
        "eras": eras,
        "era_display": era_display,
        "context": context,
        "is_future": is_future,
    }


# ── Endpoints ──────────────────────────────────────────────────────────────────

router = APIRouter(prefix="/api/v1")


@app.get("/health")
def health():
    return {"status": "ok", "version": "1.0"}


@router.get("/year/{year}")
def get_year(year: int):
    return _build_year_data(year)


@router.get("/year/{year}/buffer")
def get_year_buffer(year: int, window: int = 2):
    return {y: _build_year_data(y) for y in range(year - window, year + window + 1)}


@router.post("/reaction", status_code=201)
def post_reaction(body: ReactionBody):
    if body.reaction not in ("like", "dislike"):
        raise HTTPException(status_code=422, detail="reaction must be 'like' or 'dislike'")
    set_reaction(body.year, body.text, body.source, body.reaction)
    return {"status": "ok"}


@router.get("/reactions")
def list_reactions():
    return get_reactions()


@router.get("/saved")
def list_saved():
    return get_saved()


@router.post("/saved", status_code=201)
def post_saved(body: SaveBody):
    save_fact(body.year, body.text, body.source)
    return {"status": "ok"}


@router.delete("/saved/{key}")
def delete_saved(key: str):
    remove_saved(key)
    return {"status": "ok"}


@router.get("/eras")
def list_eras():
    return get_era_exposure()


@router.delete("/cache")
def clear_cache():
    """Wipe the event cache so all years get re-fetched with current filters.
    Use after deploying filter improvements."""
    db = get_db()
    try:
        db.execute("DELETE FROM event_cache")
        db.commit()
        return {"status": "ok", "message": "event_cache cleared — warmer will refill at 5s/year"}
    finally:
        db.close()


@router.get("/cache/status")
def cache_status():
    """How many years are currently cached (non-expired)."""
    from clockapp.server.config import settings as s
    ttl_seconds = s.cache_ttl_days * 24 * 3600
    db = get_db()
    try:
        cached = db.execute(
            "SELECT COUNT(DISTINCT year) FROM event_cache WHERE fetched_at > ?",
            (datetime.datetime.now().timestamp() - ttl_seconds,),
        ).fetchone()[0]
    finally:
        db.close()
    total_years = 1440
    return {
        "cached_years": cached,
        "total_years": total_years,
        "percent_warm": round(cached / total_years * 100, 1),
    }


@router.get("/now")
def get_now(tz: str | None = None):
    if tz is not None:
        try:
            zone = zoneinfo.ZoneInfo(tz)
        except (zoneinfo.ZoneInfoNotFoundError, KeyError):
            raise HTTPException(status_code=400, detail=f"Invalid timezone: {tz}")
        now = datetime.datetime.now(zone)
    else:
        now = datetime.datetime.now(datetime.timezone.utc)

    hour = now.hour
    minute = now.minute
    year = hour * 100 + minute
    day_of_year = now.timetuple().tm_yday
    time_str = now.strftime("%H:%M")

    is_future = year > settings.current_year
    context = get_context_for_year(year)
    eras = get_eras_for_year(year)

    era = eras[0]["name"] if eras else None
    ongoing = None
    if len(eras) >= 2 and eras[1]["name"] != era:
        ongoing = eras[1]["name"]

    if is_future:
        future_events = get_future_events_for_year(year)
        if future_events:
            event_dict = future_events[day_of_year % len(future_events)]
            event = event_dict.get("text", context)
            source = event_dict.get("source")
        else:
            event = context
            source = None
        source_url = None
    else:
        events = get_events_for_year(year)
        if events:
            event_dict = events[day_of_year % len(events)]
            event = event_dict.get("text", context)
            source = "Wikidata"
            source_url = f"https://www.wikidata.org/wiki/Special:Search?search={year}"
        else:
            event = context
            source = None
            source_url = None

    return {
        "time": time_str,
        "year": year,
        "event": event,
        "context": context,
        "era": era,
        "ongoing": ongoing,
        "source": source,
        "source_url": source_url,
    }


app.include_router(router)
