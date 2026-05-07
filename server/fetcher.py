"""Wikidata fetching logic, adapted from clock.py."""

import re
import urllib.parse

import requests

from clockapp.server.config import settings
from clockapp.server.db import get_cached_events, store_events

# Exclude known garbage entity types directly in SPARQL — much faster than
# post-filtering and avoids filling the LIMIT with useless results.
_P31_EXCLUSIONS = " ".join([
    "FILTER NOT EXISTS { ?event wdt:P31 wd:Q13406463. }",   # list article
    "FILTER NOT EXISTS { ?event wdt:P31 wd:Q14204246. }",   # Wikimedia disambiguation
    "FILTER NOT EXISTS { ?event wdt:P31 wd:Q21199. }",      # natural number
    "FILTER NOT EXISTS { ?event wdt:P31 wd:Q4167836. }",    # Wikimedia category
    "FILTER NOT EXISTS { ?event wdt:P31 wd:Q17633526. }",   # disambiguation page
    "FILTER NOT EXISTS { ?event wdt:P31 wd:Q3863. }",       # asteroid
    "FILTER NOT EXISTS { ?event wdt:P31 wd:Q202444. }",     # given name
    "FILTER NOT EXISTS { ?event wdt:P31 wd:Q61788250. }",   # one-year-period
])

SPARQL_P585 = """
SELECT DISTINCT ?eventLabel WHERE {{
  ?event wdt:P585 ?date.
  FILTER(YEAR(?date) = {{year}})
  {exclusions}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }}
}} LIMIT 20
""".format(exclusions=_P31_EXCLUSIONS).replace("{{year}}", "{year}")

SPARQL_P571 = """
SELECT DISTINCT ?eventLabel WHERE {{
  ?event wdt:P571 ?date.
  FILTER(YEAR(?date) = {{year}})
  {exclusions}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }}
}} LIMIT 15
""".format(exclusions=_P31_EXCLUSIONS).replace("{{year}}", "{year}")

HEADERS = {"User-Agent": "YearClock/1.0 (educational project; historieklokka.no)"}

# Patterns that identify labels as uninteresting to a general human reader.
_BORING_PATTERNS = [
    # Sports participation entries
    re.compile(r'.+ at the \d{4} (Summer|Winter) Olympics?$', re.I),
    re.compile(r'.+ at the \d{4} (Summer|Winter) Paralympic Games?$', re.I),
    re.compile(r'.+ at the \d{4} (Summer|Winter) Youth Olympics?$', re.I),
    re.compile(r'.+ at the \d{4} Commonwealth Games?$', re.I),
    re.compile(r'.+ at the \d{4} (FIFA|UEFA|FIBA|IAAF|UCI|IIHF).*$', re.I),
    re.compile(r'\d{4}[-–]\d{2,4} .*(season|league|championship|cup)$', re.I),
    # Calendar / meta time entries
    re.compile(r'^(January|February|March|April|May|June|July|August|'
               r'September|October|November|December) \d{4}$', re.I),
    re.compile(r'^\d{4} in ', re.I),
    re.compile(r'one-year-period', re.I),
    re.compile(r'^\d{3,4}[-–]\d{2,4}$'),            # "939-940" pure date range
    # Astronomical catalog objects (not interesting without context)
    re.compile(r'^NGC \d+', re.I),
    re.compile(r'^IC \d+$', re.I),
    re.compile(r'^(Messier|M) \d+$', re.I),
    re.compile(r'^\(\d{2,}\) \w'),                   # "(939) Isberga" asteroid
    re.compile(r'\bmain.belt asteroid\b', re.I),
    re.compile(r'\bnear.Earth (asteroid|object)\b', re.I),
    # Technical / hardware
    re.compile(r'\bSocket \d+\b', re.I),
    # Wikimedia meta
    re.compile(r'^Category:', re.I),
    re.compile(r'^(Talk|User|File|Template|Help|Portal):', re.I),
    # Internet / fiction wikis
    re.compile(r'^SCP-\d+', re.I),
    # Standards and codes
    re.compile(r'reserved for private use', re.I),
    re.compile(r'\bISO \d+\b.*\bstandard\b', re.I),
    # Route numbers and infrastructure codes
    re.compile(r'^(Route|Highway|Road|Interstate|U\.S\. Route) \d+$', re.I),
    # Pure number or short code
    re.compile(r'^\d+$'),
    re.compile(r'^\d{3,4}$'),
]

# Regex to detect bare Q-codes (e.g. "Q23422") — not human-readable labels.
_Q_CODE_RE = re.compile(r'^Q\d+$')


def _is_interesting_label(label: str) -> bool:
    """Return True only if the label is likely to be interesting to a human reader."""
    label = label.strip()
    # Bare Wikidata Q-code — entity has no English label
    if _Q_CODE_RE.match(label):
        return False
    # Must contain at least one space (reject single-word/number labels)
    if ' ' not in label:
        return False
    # Must be long enough to convey meaningful information
    if len(label) < 20:
        return False
    # Must not match any of the known boring patterns
    if any(p.search(label) for p in _BORING_PATTERNS):
        return False
    return True


def _run_query(template: str, year: int) -> list[str]:
    try:
        query = template.format(year=year).strip()
        url = f"{settings.sparql_endpoint}?format=json&query={urllib.parse.quote(query)}"
        resp = requests.get(url, headers=HEADERS, timeout=10)
        if not resp.ok:
            return []
        bindings = resp.json().get("results", {}).get("bindings", [])
        return [
            b["eventLabel"]["value"]
            for b in bindings
            if "eventLabel" in b and _is_interesting_label(b["eventLabel"]["value"])
        ]
    except (requests.RequestException, ValueError, KeyError):
        return []


def fetch_wikidata_events(year: int) -> list[str]:
    """Run both SPARQL queries, deduplicate, and filter uninteresting labels."""
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
