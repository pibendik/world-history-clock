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
# SPARQL query templates — kept as lean as possible.
# All heavyweight filtering is done in Python post-processing (_is_interesting_label).
# The SPARQL FILTER NOT EXISTS clauses were removed because they made queries
# too expensive for Wikidata's public endpoint (25+ second response times).
# ---------------------------------------------------------------------------

SPARQL_P585 = (
    "SELECT DISTINCT ?event ?eventLabel WHERE {\n"
    "  ?event wdt:P585 ?date.\n"
    "  FILTER(YEAR(?date) = {year})\n"
    "  SERVICE wikibase:label { bd:serviceParam wikibase:language \"en\". }\n"
    "} LIMIT 30"
)

SPARQL_P571 = (
    "SELECT DISTINCT ?event ?eventLabel WHERE {\n"
    "  ?event wdt:P571 ?date.\n"
    "  FILTER(YEAR(?date) = {year})\n"
    "  SERVICE wikibase:label { bd:serviceParam wikibase:language \"en\". }\n"
    "} LIMIT 20"
)

# Dedicated query for notable humans — births AND deaths in the year.
# For recent years (post-1850) add a sitelinks floor to prefer globally
# notable people over obscure local figures.
SPARQL_HUMANS_MODERN = (
    "SELECT DISTINCT ?event ?eventLabel WHERE {\n"
    "  { ?event wdt:P569 ?date. } UNION { ?event wdt:P570 ?date. }\n"
    "  FILTER(YEAR(?date) = {year})\n"
    "  ?event wdt:P31 wd:Q5.\n"
    "  ?event wikibase:sitelinks ?links.\n"
    "  FILTER(?links >= 20)\n"
    "  SERVICE wikibase:label { bd:serviceParam wikibase:language \"en\". }\n"
    "} ORDER BY DESC(?links) LIMIT 15"
)

SPARQL_HUMANS = (
    "SELECT DISTINCT ?event ?eventLabel WHERE {\n"
    "  { ?event wdt:P569 ?date. } UNION { ?event wdt:P570 ?date. }\n"
    "  FILTER(YEAR(?date) = {year})\n"
    "  ?event wdt:P31 wd:Q5.\n"
    "  ?event wikibase:sitelinks ?links.\n"
    "  FILTER(?links >= 5)\n"
    "  SERVICE wikibase:label { bd:serviceParam wikibase:language \"en\". }\n"
    "} ORDER BY DESC(?links) LIMIT 15"
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
            resp = requests.get(url, headers=HEADERS, timeout=30)
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


def _wikipedia_article_title(year: int) -> str | None:
    """Return the Wikipedia article title for a year, or None if out of range."""
    if year > 2100 or year < -800:
        return None
    if year <= 0:
        return f"{abs(year)} BC"
    if year < 1000:
        return f"{year} AD"
    return str(year)


_WIKITEXT_LINK_RE = re.compile(r'\[\[(?:[^|\]]*\|)?([^\]]+)\]\]')
_WIKITEXT_TEMPLATE_RE = re.compile(r'\{\{[^{}]*\}\}')
_WIKITEXT_REF_RE = re.compile(r'<ref[^>]*/?>.*?</ref>|<ref[^/][^>]*/>', re.DOTALL)
_WIKITEXT_TAG_RE = re.compile(r'<[^>]+>')
_WIKITEXT_BOLD_RE = re.compile(r"'''?")
_DATE_PREFIX_RE = re.compile(r'^.*?(?:\d{1,2})\s*[–\-&ndash;]+\s*', re.DOTALL)


def _clean_wikitext(text: str) -> str:
    """Strip wiki markup and return plain text."""
    text = _WIKITEXT_REF_RE.sub('', text)
    text = _WIKITEXT_LINK_RE.sub(r'\1', text)
    # Remove templates iteratively (nested templates)
    for _ in range(5):
        text, n = _WIKITEXT_TEMPLATE_RE.subn('', text)
        if n == 0:
            break
    text = _WIKITEXT_TAG_RE.sub('', text)
    text = _WIKITEXT_BOLD_RE.sub('', text)
    text = text.replace('&ndash;', '–').replace('&mdash;', '—').replace('&amp;', '&')
    # Remove leading date prefix like "January 4 –"
    text = re.sub(r'^(?:[A-Z][a-z]+ \d{1,2}\s*)?[–\-]+\s*', '', text)
    return text.strip().strip('.')


def fetch_wikipedia_events(year: int) -> list[str]:
    """
    Fetch events from Wikipedia's year article.
    Returns a list of plain-text event strings.
    Works for years roughly -800 to 2100; returns [] for out-of-range or sparse years.
    """
    title = _wikipedia_article_title(year)
    if not title:
        return []

    try:
        # Step 1: get section list to find Events section index
        sections_resp = requests.get(
            "https://en.wikipedia.org/w/api.php",
            params={"action": "parse", "page": title, "prop": "sections", "format": "json"},
            headers=HEADERS,
            timeout=8,
        )
        if not sections_resp.ok:
            return []
        sections_data = sections_resp.json().get("parse", {})
        if not sections_data:
            return []

        sections = sections_data.get("sections", [])
        # Find the Events section (section 1 in most year articles)
        events_section = next(
            (s for s in sections if s.get("line", "").lower() in ("events", "events and trends")),
            sections[0] if sections else None,
        )
        if not events_section:
            return []

        section_index = events_section["index"]

        # Step 2: get wikitext for that section
        wikitext_resp = requests.get(
            "https://en.wikipedia.org/w/api.php",
            params={
                "action": "parse",
                "page": title,
                "prop": "wikitext",
                "section": section_index,
                "format": "json",
            },
            headers=HEADERS,
            timeout=8,
        )
        if not wikitext_resp.ok:
            return []

        wikitext = wikitext_resp.json().get("parse", {}).get("wikitext", {}).get("*", "")
        bullets = re.findall(r'^\*+\s*(.+)$', wikitext, re.MULTILINE)

        events: list[str] = []
        for b in bullets:
            clean = _clean_wikitext(b)
            if _is_interesting_label(clean):
                events.append(clean[:250])

        logger.debug("Wikipedia: year %d → %d events from section %s", year, len(events), section_index)
        return events[:25]

    except (requests.RequestException, ValueError, KeyError, StopIteration) as exc:
        logger.warning("Wikipedia fetch failed for year %d: %s", year, exc)
        return []


def fetch_wikidata_events(year: int) -> list[str]:
    """
    Fetch events: try Wikipedia first (fast and reliable), then fall back to
    Wikidata SPARQL (slower, may be rate-limited).
    """
    labels = fetch_wikipedia_events(year)
    if not labels:
        # Wikidata SPARQL fallback — slower but covers gaps (e.g., births/deaths)
        humans_template = SPARQL_HUMANS_MODERN if year > 1850 else SPARQL_HUMANS
        labels1 = _run_query(SPARQL_P585, year)
        labels2 = _run_query(humans_template, year)
        labels3 = _run_query(SPARQL_P571, year)
        seen: set[str] = set()
        labels = []
        for label in labels1 + labels2 + labels3:
            if label not in seen:
                seen.add(label)
                labels.append(label)
    return score_events(year, labels)


def get_events_for_year(year: int) -> list[dict]:
    """Return cached events or fetch (Wikipedia first, Wikidata SPARQL fallback).
    Returns list of {text, source} dicts."""
    cached = get_cached_events(year)
    if cached is not None:
        return cached
    labels = fetch_wikidata_events(year)
    events = [{"text": t, "source": "Wikipedia"} for t in labels]
    if events:
        store_events(year, events)
    return events
