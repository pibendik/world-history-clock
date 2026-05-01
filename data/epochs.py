import json
from pathlib import Path

_DATA_FILE = Path(__file__).parent / "epochs.json"

def _load_eras() -> list[dict]:
    with open(_DATA_FILE, encoding="utf-8") as f:
        return json.load(f)


def get_eras_for_year(year: int) -> list[dict]:
    """Return all eras that include this year, sorted by weight descending."""
    eras = _load_eras()
    matching = [era for era in eras if era["start"] <= year <= era["end"]]
    return sorted(matching, key=lambda e: e["weight"], reverse=True)


def format_era_display(year: int) -> str:
    """Return a short display string like 'Viking Age · High Middle Ages' or empty string."""
    eras = get_eras_for_year(year)
    if not eras:
        return ""
    top = eras[:2]
    return " · ".join(e["name"] for e in top)
