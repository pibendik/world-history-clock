import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from clockapp.data.epochs import format_era_display, get_eras_for_year
from clockapp.server.db import (
    get_era_exposure,
    get_reactions,
    get_saved,
    increment_era_exposure,
    remove_saved,
    save_fact,
    set_reaction,
)
from clockapp.server.fetcher import get_events_for_year

app = FastAPI(title="YearClock API", version="1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_CURRENT_YEAR = 2025


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
    is_future = year > _CURRENT_YEAR
    events = [] if is_future else get_events_for_year(year)
    eras = get_eras_for_year(year)
    era_display = format_era_display(year)

    if eras:
        increment_era_exposure(eras[0]["name"])

    return {
        "year": year,
        "events": events,
        "eras": eras,
        "era_display": era_display,
        "is_future": is_future,
    }


# ── Endpoints ──────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok", "version": "1.0"}


@app.get("/year/{year}")
def get_year(year: int):
    return _build_year_data(year)


@app.get("/year/{year}/buffer")
def get_year_buffer(year: int, window: int = 2):
    return {y: _build_year_data(y) for y in range(year - window, year + window + 1)}


@app.post("/reaction", status_code=201)
def post_reaction(body: ReactionBody):
    if body.reaction not in ("like", "dislike"):
        raise HTTPException(status_code=422, detail="reaction must be 'like' or 'dislike'")
    set_reaction(body.year, body.text, body.source, body.reaction)
    return {"status": "ok"}


@app.get("/reactions")
def list_reactions():
    return get_reactions()


@app.get("/saved")
def list_saved():
    return get_saved()


@app.post("/saved", status_code=201)
def post_saved(body: SaveBody):
    save_fact(body.year, body.text, body.source)
    return {"status": "ok"}


@app.delete("/saved/{key}")
def delete_saved(key: str):
    remove_saved(key)
    return {"status": "ok"}


@app.get("/eras")
def list_eras():
    return get_era_exposure()
