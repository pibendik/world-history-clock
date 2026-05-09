import json
import os
from pathlib import Path

_DATA_DIR = Path(__file__).parent

def _lang() -> str:
    return os.getenv("YEARCLOCK_LANG", "en")

def _lang_file(base: str) -> Path:
    """Return language-specific file path, falling back to English if not found."""
    lang = _lang()
    if lang != "en":
        candidate = _DATA_DIR / f"{Path(base).stem}.{lang}{Path(base).suffix}"
        if candidate.exists():
            return candidate
    return _DATA_DIR / base


def _load_eras() -> list[dict]:
    with open(_lang_file("epochs.json"), encoding="utf-8") as f:
        return json.load(f)


def _load_context() -> list[dict]:
    with open(_lang_file("era_context.json"), encoding="utf-8") as f:
        return json.load(f)


_future_events_cache: dict | None = None
_future_events_lang: str | None = None

def _load_future_events() -> dict:
    global _future_events_cache, _future_events_lang
    current_lang = _lang()
    if _future_events_cache is None or _future_events_lang != current_lang:
        with open(_lang_file("future_events.json"), encoding="utf-8") as f:
            raw = json.load(f)
        _future_events_cache = {
            int(k): v for k, v in raw.items() if not k.startswith("_")
        }
        _future_events_lang = current_lang
    return _future_events_cache


def get_future_events_for_year(year: int) -> list[dict]:
    """Return curated future events for a given year, or empty list."""
    return _load_future_events().get(year, [])


def get_all_eras() -> list[dict]:
    """Return all eras (for the /config API endpoint)."""
    return _load_eras()


def get_eras_for_year(year: int) -> list[dict]:
    """Return all eras that include this year, sorted by weight descending."""
    eras = _load_eras()
    matching = [era for era in eras if era["start"] <= year <= era["end"]]
    return sorted(matching, key=lambda e: e["weight"], reverse=True)


def get_context_for_year(year: int) -> str | None:
    """Return the most specific (shortest span) vivid context sentence for a year."""
    entries = _load_context()
    matching = [e for e in entries if e["from"] <= year <= e["to"]]
    if not matching:
        return None
    best = min(matching, key=lambda e: e["to"] - e["from"])
    return best["text"]


def format_era_display(year: int) -> str:
    """Return a short display string like 'Viking Age · High Middle Ages' or empty string."""
    eras = get_eras_for_year(year)
    if not eras:
        return ""
    top = eras[:2]
    return " / ".join(e["name"] for e in top)
