#!/usr/bin/env python3
"""What Year Does It Look Like? — Maps current military time HH:MM to a year."""

import os
import sys
import time
import random
import urllib.parse
import requests
from datetime import datetime

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

SPARQL_TEMPLATE = """
SELECT ?event ?eventLabel WHERE {{
  ?event wdt:P585 ?date.
  FILTER(YEAR(?date) = {year})
  FILTER NOT EXISTS {{ ?event wdt:P31 wd:Q13406463. }}
  FILTER NOT EXISTS {{ ?event wdt:P31 wd:Q14204246. }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }}
}} LIMIT 10
"""


def clear():
    os.system("cls" if os.name == "nt" else "clear")


def derive_year(hh: int, mm: int) -> int:
    return int(f"{hh:02d}{mm:02d}")


def fetch_wikidata(year: int) -> str | None:
    """Primary: Wikidata SPARQL — returns a random event label for the year."""
    try:
        query = SPARQL_TEMPLATE.format(year=year).strip()
        url = (
            "https://query.wikidata.org/sparql"
            f"?format=json&query={urllib.parse.quote(query)}"
        )
        resp = requests.get(url, headers=WIKIDATA_HEADERS, timeout=8)
        if not resp.ok:
            return None
        bindings = resp.json().get("results", {}).get("bindings", [])
        labels = [
            b["eventLabel"]["value"]
            for b in bindings
            if "eventLabel" in b and not b["eventLabel"]["value"].startswith("Q")
        ]
        if labels:
            return random.choice(labels)
        return None
    except (requests.RequestException, ValueError, KeyError):
        return None


def fetch_wikipedia(year: int) -> str | None:
    """Fallback: Wikipedia REST summary for the year page."""
    try:
        url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{year}"
        resp = requests.get(url, headers=WIKIDATA_HEADERS, timeout=8)
        if not resp.ok:
            return None
        extract = resp.json().get("extract", "").strip()
        if extract and len(extract) > 20:
            # Trim to ~2 sentences so it fits the display
            sentences = extract.split(". ")
            return ". ".join(sentences[:2]) + ("." if len(sentences) > 1 else "")
        return None
    except (requests.RequestException, ValueError, KeyError):
        return None


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
    fact = fetch_wikidata(year)
    if fact:
        return fact, True, "Wikidata"
    fact = fetch_wikipedia(year)
    if fact:
        return fact, True, "Wikipedia"
    fact = fetch_numbersapi(year)
    if fact:
        return fact, True, "Numbers API"
    return None, False, None


def year_label(year: int) -> str:
    if year == 0:
        return f"{BOLD}Year 0 / Antiquity{RESET}"
    if year > 2025:
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
        print(f"  {RED}(No data — all sources unreachable){RESET}")
    else:
        print(f"  {YELLOW}(Fetching…){RESET}")

    print()
    print(f"{CYAN}{BOLD}{'─' * 52}{RESET}")
    print(f"{DIM}  Ctrl+C to quit{RESET}")


def main():
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
