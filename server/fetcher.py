"""Event fetching logic for the YearClock API."""

import logging
import re

import requests

from clockapp.server.config import settings
from clockapp.server.db import get_cached_events, store_events
from clockapp.server.scorer import score_events

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# SPARQL query template — kept only for the /api/v1/debug/sparql diagnostic
# endpoint. SPARQL is no longer used for production event fetching; it reliably
# times out (30s+) on Wikidata's public endpoint for year-filtered queries.
# ---------------------------------------------------------------------------

SPARQL_P585 = (
    "SELECT DISTINCT ?event ?eventLabel WHERE {\n"
    "  ?event wdt:P585 ?date.\n"
    "  FILTER(YEAR(?date) = {year})\n"
    "  SERVICE wikibase:label { bd:serviceParam wikibase:language \"en\". }\n"
    "} LIMIT 30"
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


def _wikipedia_article_title(year: int) -> str | None:
    """Return the Wikipedia article title for a year, or None if out of range."""
    if year <= 0 or year > 2100:
        return None
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
    Works for years roughly 1 to 2100; returns [] for out-of-range or sparse years.

    Uses a single API call (action=query with rvprop=content) to fetch full wikitext,
    then extracts the Events section via regex. This approach correctly handles redirect
    articles (e.g. "701 AD" → "701") that the deprecated prop=sections API misses.
    """
    title = _wikipedia_article_title(year)
    if not title:
        return []

    try:
        resp = requests.get(
            "https://en.wikipedia.org/w/api.php",
            params={
                "action": "query",
                "prop": "revisions",
                "rvprop": "content",
                "rvslots": "main",
                "titles": title,
                "redirects": 1,
                "format": "json",
            },
            headers=HEADERS,
            timeout=12,
        )
        if not resp.ok:
            logger.warning("Wikipedia HTTP %s for year %d", resp.status_code, year)
            return []

        pages = resp.json().get("query", {}).get("pages", {})
        page = next(iter(pages.values()), {})
        # -1 pageid means article not found
        if page.get("pageid", -1) == -1:
            return []
        wikitext = (
            page.get("revisions", [{}])[0]
            .get("slots", {})
            .get("main", {})
            .get("*", "")
        )
        if not wikitext:
            return []

        # Extract the Events section (handles "Events", "Events and trends", etc.)
        m = re.search(
            r'==\s*Events(?:\s+and\s+\w+)?\s*==(.+?)(?:^==[^=]|\Z)',
            wikitext,
            re.DOTALL | re.MULTILINE,
        )
        if not m:
            # No Events section → article is not a year article (vandalism, redirect to
            # unrelated topic, etc.).  Return [] so era-context fallback handles it cleanly.
            logger.info("Wikipedia: year %d — no Events section found (title=%r)", year, title)
            return []
        section = m.group(1)
        bullets = re.findall(r'^\*+\s*(.+)$', section, re.MULTILINE)

        events: list[str] = []
        for b in bullets:
            clean = _clean_wikitext(b)
            if _is_interesting_label(clean):
                events.append(clean[:250])

        logger.debug("Wikipedia: year %d → %d events", year, len(events))
        if not events:
            logger.info("Wikipedia: year %d — article found but 0 usable events (title=%r)", year, title)
        return events[:25]

    except (requests.RequestException, ValueError, KeyError, StopIteration) as exc:
        logger.warning("Wikipedia fetch failed for year %d: %s", year, exc)
        return []


def fetch_wikidata_events(year: int) -> list[dict]:
    """
    Fetch events from Wikipedia's year article.
    Returns scored/rephrased event dicts, or [] if no article exists.

    Wikidata SPARQL is no longer used — it reliably times out (30s+) for
    year-filtered queries regardless of rate limiting. Era context handles
    sparse/missing years gracefully.
    """
    title = _wikipedia_article_title(year)
    if not title:
        return []

    labels = fetch_wikipedia_events(year)
    return score_events(year, labels)


def get_events_for_year(year: int) -> list[dict]:
    """Return cached events or fetch from Wikipedia.
    Returns list of {text, source, original?} dicts."""
    cached = get_cached_events(year)
    if cached is not None:
        return cached
    scored = fetch_wikidata_events(year)
    events = []
    for item in scored:
        event = {"text": item.get("text", ""), "source": "Wikipedia"}
        if "original" in item:
            event["original"] = item["original"]
        events.append(event)
    events = [e for e in events if e["text"]]
    if events:
        store_events(year, events)
    return events
