"""Wikidata fetching logic, adapted from clock.py."""

import re
import urllib.parse

import requests

from clockapp.server.config import settings
from clockapp.server.db import get_cached_events, store_events
from clockapp.server.scorer import score_events

# ---------------------------------------------------------------------------
# SPARQL-level exclusions — stop boring types from consuming LIMIT slots
# ---------------------------------------------------------------------------
_P31_EXCLUSIONS = " ".join([
    "FILTER NOT EXISTS { ?event wdt:P31 wd:Q13406463. }",   # list article
    "FILTER NOT EXISTS { ?event wdt:P31 wd:Q14204246. }",   # Wikimedia disambiguation
    "FILTER NOT EXISTS { ?event wdt:P31 wd:Q21199. }",      # natural number
    "FILTER NOT EXISTS { ?event wdt:P31 wd:Q4167836. }",    # Wikimedia category
    "FILTER NOT EXISTS { ?event wdt:P31 wd:Q17633526. }",   # disambiguation page
    "FILTER NOT EXISTS { ?event wdt:P31 wd:Q3863. }",       # asteroid
    "FILTER NOT EXISTS { ?event wdt:P31 wd:Q202444. }",     # given name
    "FILTER NOT EXISTS { ?event wdt:P31 wd:Q61788250. }",   # one-year-period
    # Astronomical events — common and rarely interesting to a general audience
    "FILTER NOT EXISTS { ?event wdt:P31 wd:Q188025. }",     # solar eclipse
    "FILTER NOT EXISTS { ?event wdt:P31 wd:Q3234690. }",    # lunar eclipse
    "FILTER NOT EXISTS { ?event wdt:P31 wd:Q645883. }",     # occultation
    "FILTER NOT EXISTS { ?event wdt:P31 wd:Q17524420. }",   # aspect (astrology/astronomy)
    "FILTER NOT EXISTS { ?event wdt:P31 wd:Q107024. }",     # meteor shower
    "FILTER NOT EXISTS { ?event wdt:P31 wd:Q1151284. }",    # transit of a planet
    "FILTER NOT EXISTS { ?event wdt:P31 wd:Q523. }",        # star
    "FILTER NOT EXISTS { ?event wdt:P31 wd:Q318. }",        # galaxy
    "FILTER NOT EXISTS { ?event wdt:P31 wd:Q2154519. }",    # planetary transit
])

# ---------------------------------------------------------------------------
# SPARQL query templates
# ---------------------------------------------------------------------------

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

# Dedicated query for notable humans — births AND deaths in the year.
# For recent years (post-1850) add a sitelinks floor to prefer globally
# notable people over obscure local figures.
SPARQL_HUMANS_MODERN = """
SELECT DISTINCT ?eventLabel WHERE {{
  {{ ?event wdt:P569 ?date. }} UNION {{ ?event wdt:P570 ?date. }}
  FILTER(YEAR(?date) = {{year}})
  ?event wdt:P31 wd:Q5.
  ?event wdt:P21 [].
  ?event wikibase:sitelinks ?links.
  FILTER(?links >= 20)
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }}
}} ORDER BY DESC(?links) LIMIT 15
""".replace("{{year}}", "{year}")

SPARQL_HUMANS = """
SELECT DISTINCT ?eventLabel WHERE {{
  {{ ?event wdt:P569 ?date. }} UNION {{ ?event wdt:P570 ?date. }}
  FILTER(YEAR(?date) = {{year}})
  ?event wdt:P31 wd:Q5.
  ?event wdt:P21 [].
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }}
}} LIMIT 15
""".replace("{{year}}", "{year}")

HEADERS = {"User-Agent": "YearClock/1.0 (educational project; historieklokka.no)"}

# ---------------------------------------------------------------------------
# Label-level boring-pattern filter
# ---------------------------------------------------------------------------
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
    # Astronomical events (belt-and-suspenders: SPARQL exclusions are primary)
    re.compile(r'^(Solar|Lunar) eclipse of ', re.I),
    re.compile(r'^Transit of (Mercury|Venus|Mars)', re.I),
    re.compile(r'^Occultation of ', re.I),
    re.compile(r'^(Annular|Total|Partial|Hybrid) (solar|lunar) eclipse', re.I),
    # Astronomical catalog objects
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

_Q_CODE_RE = re.compile(r'^Q\d+$')


def _is_interesting_label(label: str) -> bool:
    """Return True only if the label is likely to be interesting to a human reader."""
    label = label.strip()
    if _Q_CODE_RE.match(label):
        return False
    if ' ' not in label:
        return False
    if len(label) < 20:
        return False
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
    """
    Run three SPARQL queries, deduplicate, and filter uninteresting labels.
    Query order determines display priority:
      1. P585 (point in time) — actual events, discoveries, battles, etc.
      2. Notable humans (births/deaths) — almost always interesting
      3. P571 (inception) — institutions, buildings, organisations founded

    For years after 1850, the humans query requires >= 20 sitelinks
    (cross-language Wikipedia presence as a notability proxy) to avoid
    minor local figures swamping the results for data-rich modern years.
    """
    humans_template = SPARQL_HUMANS_MODERN if year > 1850 else SPARQL_HUMANS
    labels1 = _run_query(SPARQL_P585, year)
    labels2 = _run_query(humans_template, year)
    labels3 = _run_query(SPARQL_P571, year)
    seen: set[str] = set()
    combined: list[str] = []
    for label in labels1 + labels2 + labels3:
        if label not in seen:
            seen.add(label)
            combined.append(label)
    return score_events(year, combined)


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
