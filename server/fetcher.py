"""Wikidata fetching logic, adapted from clock.py."""

import re
import urllib.parse

import requests

from clockapp.server.config import settings
from clockapp.server.db import get_cached_events, store_events

SPARQL_P585 = """
SELECT DISTINCT ?eventLabel WHERE {{
  ?event wdt:P585 ?date.
  FILTER(YEAR(?date) = {year})
  FILTER NOT EXISTS {{ ?event wdt:P31 wd:Q13406463. }}
  FILTER NOT EXISTS {{ ?event wdt:P31 wd:Q14204246. }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }}
}} LIMIT 15
"""

SPARQL_P571 = """
SELECT DISTINCT ?eventLabel WHERE {{
  ?event wdt:P571 ?date.
  FILTER(YEAR(?date) = {year})
  FILTER NOT EXISTS {{ ?event wdt:P31 wd:Q13406463. }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }}
}} LIMIT 10
"""

HEADERS = {"User-Agent": "YearClock/1.0 (educational project)"}

_BORING_PATTERNS = [
    re.compile(r'.+ at the \d{4} (Summer|Winter) Olympics?$', re.I),
    re.compile(r'.+ at the \d{4} (Summer|Winter) Paralympic Games?$', re.I),
    re.compile(r'.+ at the \d{4} (Summer|Winter) Youth Olympics?$', re.I),
    re.compile(r'.+ at the \d{4} Commonwealth Games?$', re.I),
    re.compile(r'.+ at the \d{4} (FIFA|UEFA|FIBA|IAAF|UCI).*$', re.I),
    re.compile(r'\d{4}[-–]\d{2,4} .*(season|league|championship)$', re.I),
    re.compile(r'^(January|February|March|April|May|June|July|August|September|October|November|December) \d{4}$', re.I),
    re.compile(r'^\d{4} in ', re.I),
]


def _is_boring_label(label: str) -> bool:
    return any(p.search(label) for p in _BORING_PATTERNS)


def _run_query(template: str, year: int) -> list[str]:
    try:
        query = template.format(year=year).strip()
        url = f"{settings.sparql_endpoint}?format=json&query={urllib.parse.quote(query)}"
        resp = requests.get(url, headers=HEADERS, timeout=8)
        if not resp.ok:
            return []
        bindings = resp.json().get("results", {}).get("bindings", [])
        return [
            b["eventLabel"]["value"]
            for b in bindings
            if "eventLabel" in b
            and not b["eventLabel"]["value"].startswith("Q")
            and len(b["eventLabel"]["value"]) >= 15
            and not _is_boring_label(b["eventLabel"]["value"])
        ]
    except (requests.RequestException, ValueError, KeyError):
        return []


def fetch_wikidata_events(year: int) -> list[str]:
    """Run both SPARQL queries, deduplicate, and filter boring labels."""
    labels1 = _run_query(SPARQL_P585, year)
    labels2 = _run_query(SPARQL_P571, year)
    seen: set[str] = set()
    combined: list[str] = []
    for label in labels1 + labels2:
        if label not in seen:
            seen.add(label)
            combined.append(label)
    return combined


def get_events_for_year(year: int) -> list[dict]:
    """Return cached events or fetch from Wikidata. Returns list of {text, source} dicts."""
    cached = get_cached_events(year)
    if cached is not None:
        return cached
    labels = fetch_wikidata_events(year)
    events = [{"text": t, "source": "Wikidata"} for t in labels]
    if events:
        store_events(year, events)
    return events
