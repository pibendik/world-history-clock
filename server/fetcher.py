"""Wikidata fetching logic, adapted from clock.py."""

import logging
import re
import threading
import time
import urllib.parse

import requests

from clockapp.server.config import settings
from clockapp.server.db import get_cached_events, store_events
from clockapp.server.scorer import score_events

logger = logging.getLogger(__name__)

# Serialize ALL outbound SPARQL requests so only one is in-flight at a time.
# Without this, the warmer thread + concurrent user requests all pile up on
# Wikidata simultaneously, causing cascading 429s and ReadTimeouts.
_sparql_lock = threading.Lock()

# Minimum seconds to wait between queries — even when Wikidata isn't complaining.
_MIN_QUERY_INTERVAL = 3.0
_last_query_time: float = 0.0

# When Wikidata returns 429, record when we're allowed to try again.
_rate_limit_until: float = 0.0

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

SPARQL_P571 = (
    "SELECT DISTINCT ?eventLabel WHERE {\n"
    "  ?event wdt:P571 ?date.\n"
    "  FILTER(YEAR(?date) = {year})\n"
    + "\n".join(f"  {f}" for f in _P31_EXCLUSIONS.split("\n") if f.strip()) + "\n"
    "  SERVICE wikibase:label { bd:serviceParam wikibase:language \"en\". }\n"
    "} LIMIT 15"
)

# Dedicated query for notable humans — births AND deaths in the year.
# For recent years (post-1850) add a sitelinks floor to prefer globally
# notable people over obscure local figures.
SPARQL_HUMANS_MODERN = (
    "SELECT DISTINCT ?eventLabel WHERE {\n"
    "  { ?event wdt:P569 ?date. } UNION { ?event wdt:P570 ?date. }\n"
    "  FILTER(YEAR(?date) = {year})\n"
    "  ?event wdt:P31 wd:Q5.\n"
    "  ?event wdt:P21 [].\n"
    "  ?event wikibase:sitelinks ?links.\n"
    "  FILTER(?links >= 20)\n"
    "  SERVICE wikibase:label { bd:serviceParam wikibase:language \"en\". }\n"
    "} ORDER BY DESC(?links) LIMIT 15"
)

SPARQL_HUMANS = (
    "SELECT DISTINCT ?eventLabel WHERE {\n"
    "  { ?event wdt:P569 ?date. } UNION { ?event wdt:P570 ?date. }\n"
    "  FILTER(YEAR(?date) = {year})\n"
    "  ?event wdt:P31 wd:Q5.\n"
    "  ?event wdt:P21 [].\n"
    "  SERVICE wikibase:label { bd:serviceParam wikibase:language \"en\". }\n"
    "} LIMIT 15"
)

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
    global _rate_limit_until, _last_query_time
    with _sparql_lock:
        now = time.time()
        if now < _rate_limit_until:
            wait = int(_rate_limit_until - now)
            logger.debug("Skipping SPARQL for year %d — rate-limited for %ds more", year, wait)
            return []
        # Enforce minimum spacing — avoids pileup even without a 429.
        gap = _MIN_QUERY_INTERVAL - (now - _last_query_time)
        if gap > 0:
            time.sleep(gap)
        _last_query_time = time.time()
        try:
            query = template.replace("{year}", str(year)).strip()
            url = f"{settings.sparql_endpoint}?format=json&query={urllib.parse.quote(query)}"
            resp = requests.get(url, headers=HEADERS, timeout=20)
            if resp.status_code == 429:
                retry_after = int(resp.headers.get("Retry-After", 120))
                _rate_limit_until = time.time() + retry_after
                logger.warning(
                    "Wikidata rate limited (429) for year %d — pausing %ds",
                    year, retry_after,
                )
                return []
            if not resp.ok:
                logger.warning("SPARQL HTTP %s for year %d: %s", resp.status_code, year, resp.text[:200])
                return []
            bindings = resp.json().get("results", {}).get("bindings", [])
            return [
                b["eventLabel"]["value"]
                for b in bindings
                if "eventLabel" in b and _is_interesting_label(b["eventLabel"]["value"])
            ]
        except (requests.RequestException, ValueError, KeyError) as exc:
            logger.warning("SPARQL query failed for year %d: %s: %s", year, type(exc).__name__, exc)
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
