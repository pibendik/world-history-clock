import json
from pathlib import Path

_DATA_FILE = Path(__file__).parent / "epochs.json"
_CONTEXT_FILE = Path(__file__).parent / "era_context.json"

def _load_eras() -> list[dict]:
    with open(_DATA_FILE, encoding="utf-8") as f:
        return json.load(f)


def _load_context() -> list[dict]:
    with open(_CONTEXT_FILE, encoding="utf-8") as f:
        return json.load(f)


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
    # Prefer the most specific (smallest date span) entry
    best = min(matching, key=lambda e: e["to"] - e["from"])
    return best["text"]


def format_era_display(year: int) -> str:
    """Return a short display string like 'Viking Age · High Middle Ages' or empty string."""
    eras = get_eras_for_year(year)
    if not eras:
        return ""
    top = eras[:2]
    return " / ".join(e["name"] for e in top)
