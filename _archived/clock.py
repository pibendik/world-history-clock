#!/usr/bin/env python3
"""What Year Does It Look Like? — Maps current military time HH:MM to a year."""

import json
import os
import re
import sys
import time
import urllib.parse
import requests
from datetime import datetime
from pathlib import Path

# ANSI codes
RESET  = "\033[0m"
BOLD   = "\033[1m"
CYAN   = "\033[36m"
YELLOW = "\033[33m"
GREEN  = "\033[32m"
RED    = "\033[31m"
DIM    = "\033[2m"
MAGENTA = "\033[35m"

WIKIDATA_HEADERS = {"User-Agent": "ClockApp/0.1 (educational project)"}

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


_year_cache: dict[int, dict] = {}


def clear():
    os.system("cls" if os.name == "nt" else "clear")


def derive_year(hh: int, mm: int) -> int:
    return int(f"{hh:02d}{mm:02d}")


def fetch_wikidata(year: int) -> list[str]:
    """Fetch all event labels for the year from Wikidata (P585 + P571), deduplicated."""
    def run_query(template: str) -> list[str]:
        try:
            query = template.format(year=year).strip()
            url = (
                "https://query.wikidata.org/sparql"
                f"?format=json&query={urllib.parse.quote(query)}"
            )
            resp = requests.get(url, headers=WIKIDATA_HEADERS, timeout=8)
            if not resp.ok:
                return []
            bindings = resp.json().get("results", {}).get("bindings", [])
            return [
                b["eventLabel"]["value"]
                for b in bindings
                if "eventLabel" in b and not b["eventLabel"]["value"].startswith("Q")
                and not _is_boring_label(b["eventLabel"]["value"])
            ]
        except (requests.RequestException, ValueError, KeyError):
            return []

    labels1 = run_query(SPARQL_P585)
    labels2 = run_query(SPARQL_P571)
    seen: set[str] = set()
    combined: list[str] = []
    for label in labels1 + labels2:
        if label not in seen:
            seen.add(label)
            combined.append(label)
    return combined


def get_next_event(year: int) -> str | None:
    """Return the next cached event for the year, fetching all events if not yet cached."""
    if year not in _year_cache:
        labels = fetch_wikidata(year)
        if not labels:
            return None
        _year_cache[year] = {"events": labels, "index": 0, "source": "Wikidata"}
    entry = _year_cache[year]
    if not entry["events"]:
        return None
    event = entry["events"][entry["index"] % len(entry["events"])]
    entry["index"] += 1
    return event


def fetch_numbersapi(year: int) -> str | None:
    """Tertiary: Numbers API (may be unreachable, kept as last resort)."""
    try:
        url = f"http://numbersapi.com/{year}/year"
        resp = requests.get(url, timeout=5)
        if resp.ok:
            text = resp.text.strip()
            if "no year fact" in text.lower():
                return None
            return text
        return None
    except requests.RequestException:
        return None


def fetch_fact(year: int) -> tuple[str | None, bool, str | None]:
    """Try each source in order. Returns (fact_text, network_ok, source_name)."""
    fact = get_next_event(year)
    if fact:
        return fact, True, "Wikidata"
    fact = fetch_numbersapi(year)
    if fact:
        return fact, True, "Numbers API"
    return None, False, None


def year_label(year: int) -> str:
    if year == 0:
        return f"{BOLD}Year 0 / Antiquity{RESET}"
    if year > datetime.date.today().year:
        return f"{BOLD}{MAGENTA}Year {year} — THE FUTURE{RESET}"
    era = "AD" if year > 0 else "BC"
    return f"{BOLD}Year {year} {era}{RESET}"


def word_wrap(text: str, width: int = 50, indent: str = "  ") -> list[str]:
    words = text.split()
    lines, line = [], indent
    for word in words:
        if len(line) + len(word) + 1 > width:
            lines.append(line)
            line = indent + word + " "
        else:
            line += word + " "
    if line.strip():
        lines.append(line)
    return lines


def render(now: datetime, year: int, fact: str | None, network_ok: bool, source: str | None):
    time_12 = now.strftime("%I:%M:%S %p").lstrip("0")
    time_24 = now.strftime("%H:%M:%S")
    date_str = now.strftime("%A, %B %-d %Y")

    print(f"{CYAN}{BOLD}{'─' * 52}{RESET}")
    print(f"{BOLD}  What Year Does It Look Like?{RESET}")
    print(f"{CYAN}{BOLD}{'─' * 52}{RESET}")
    print()
    print(f"  {BOLD}Time:{RESET}  {GREEN}{time_12}{RESET}   {DIM}({time_24} military){RESET}")
    print(f"  {BOLD}Date:{RESET}  {DIM}{date_str}{RESET}")
    print()
    print(f"  {BOLD}Maps to:{RESET}  {YELLOW}{year_label(year)}{RESET}")
    print()

    source_label = f"  {DIM}[via {source}]{RESET}" if source else ""
    print(f"  {BOLD}Event / fact:{RESET}{source_label}")

    if not network_ok and fact:
        print(f"  {DIM}[last known — all sources unreachable]{RESET}")

    if fact:
        for line in word_wrap(fact):
            print(f"{DIM}{line}{RESET}")
    elif not network_ok:
        print(f"  {YELLOW}(No specific records found for year {year} — try a nearby minute){RESET}")
    else:
        print(f"  {YELLOW}(Fetching…){RESET}")

    print()
    print(f"{CYAN}{BOLD}{'─' * 52}{RESET}")
    print(f"{DIM}  Press Ctrl+C to quit · Run with --saved to view saved{RESET}")


def get_log_path() -> Path:
    log_dir = Path.home() / ".clockapp"
    log_dir.mkdir(exist_ok=True)
    return log_dir / "auto_log.json"


def auto_log_entry(year: int, fact: str, source: str | None):
    """Append a new year entry to the auto-log when the year changes."""
    path = get_log_path()
    try:
        entries = json.loads(path.read_text()) if path.exists() else []
    except (json.JSONDecodeError, OSError):
        entries = []
    entries.insert(0, {
        "year": year,
        "text": fact,
        "source": source,
        "savedAt": datetime.now().isoformat(),
    })
    try:
        path.write_text(json.dumps(entries, indent=2, ensure_ascii=False))
    except OSError:
        pass


def print_saved():
    """Print all auto-logged facts and exit."""
    path = get_log_path()
    if not path.exists():
        print("No saved facts yet. Run the clock to start logging.")
        return
    try:
        entries = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        print("Could not read saved facts.")
        return
    if not entries:
        print("No saved facts yet.")
        return
    print(f"{CYAN}{BOLD}{'─' * 52}{RESET}")
    print(f"{BOLD}  Saved / Auto-logged Facts ({len(entries)}){RESET}")
    print(f"{CYAN}{BOLD}{'─' * 52}{RESET}")
    for e in entries:
        source_tag = f" [{e.get('source', '?')}]" if e.get('source') else ""
        print(f"\n  {YELLOW}Year {e['year']}{RESET}{DIM}{source_tag}{RESET}")
        for line in word_wrap(e.get('text', '(no text)')):
            print(f"{DIM}{line}{RESET}")
    print(f"\n{CYAN}{BOLD}{'─' * 52}{RESET}")


def main():
    if '--saved' in sys.argv:
        print_saved()
        return

    last_year = -1
    current_fact = None
    network_ok = True
    current_source = None

    while True:
        now = datetime.now()
        hh, mm = now.hour, now.minute
        year = derive_year(hh, mm)

        if year != last_year:
            fact, ok, source = fetch_fact(year)
            if fact:
                current_fact = fact
                network_ok = True
                current_source = source
                auto_log_entry(year, fact, source)
            else:
                network_ok = False
                current_source = None
                # keep current_fact as last known
            last_year = year

        clear()
        render(now, year, current_fact, network_ok, current_source)
        time.sleep(1)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nGoodbye!")
        sys.exit(0)
