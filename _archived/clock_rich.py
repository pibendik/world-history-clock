#!/usr/bin/env python3
"""What Year Does It Look Like? — polished Rich version."""

import sys
import threading
import time
import urllib.parse
from datetime import datetime

import requests
from rich import box
from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.text import Text

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

_year_cache: dict[int, dict] = {}

SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]


# ── Data fetching ─────────────────────────────────────────────────────────────

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
                if "eventLabel" in b
                and not b["eventLabel"]["value"].startswith("Q")
                and len(b["eventLabel"]["value"]) > 10
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


def get_next_cached_event(year: int) -> tuple[str | None, int, int]:
    """Return (event, total, shown) for the year, cycling through the full cache."""
    if year not in _year_cache:
        labels = fetch_wikidata(year)
        if not labels:
            return None, 0, 0
        _year_cache[year] = {"events": labels, "index": 0, "source": "Wikidata"}
    entry = _year_cache[year]
    if not entry["events"]:
        return None, 0, 0
    total = len(entry["events"])
    idx = entry["index"] % total
    event = entry["events"][idx]
    entry["index"] += 1
    return event, total, idx + 1


def fetch_numbersapi(year: int) -> list[str]:
    try:
        url = f"http://numbersapi.com/{year}/year"
        resp = requests.get(url, timeout=5)
        if resp.ok:
            text = resp.text.strip()
            if "no year fact" in text.lower():
                return []
            return [text]
        return []
    except requests.RequestException:
        return []


def fetch_events(year: int) -> tuple[list[str], str | None, int, int]:
    """Try each source in order; return (events, source_name, total, shown)."""
    event, total, shown = get_next_cached_event(year)
    if event:
        return [event], "Wikidata", total, shown
    events = fetch_numbersapi(year)
    if events:
        return events, "Numbers API", len(events), 1
    return [], None, 0, 0


# ── Styling helpers ───────────────────────────────────────────────────────────

def year_theme(year: int) -> dict:
    """Return color/label/note for a given year."""
    if year > 2025:
        return {"color": "bold magenta", "border": "magenta", "label": "THE FUTURE", "note": ""}
    if year < 100:
        era = "BC" if year < 0 else ("Year 0" if year == 0 else "AD")
        return {"color": "bold yellow", "border": "yellow", "label": era, "note": "sparse records"}
    era = "AD" if year >= 0 else "BC"
    return {"color": "bold cyan", "border": "cyan", "label": era, "note": ""}


# ── Layout builders ───────────────────────────────────────────────────────────

def build_header() -> Panel:
    title = Text("What Year Does It Look Like?", justify="center")
    title.stylize("bold white")
    return Panel(title, style="on navy_blue", border_style="bright_blue", box=box.HEAVY, padding=(0, 2))


def build_clock(now: datetime) -> Panel:
    time_12 = now.strftime("%I:%M:%S %p").lstrip("0")
    time_24 = now.strftime("%H:%M:%S")
    date_str = now.strftime("%A, %B %-d %Y")

    content = Text(justify="center")
    content.append(f"{time_12}\n", style="bold bright_green")
    content.append(f"{time_24}", style="dim green")
    content.append("  military\n\n", style="dim")
    content.append(date_str, style="dim white")

    return Panel(
        content,
        title="[bold green]Time[/bold green]",
        border_style="green",
        box=box.ROUNDED,
        padding=(1, 2),
    )


def build_year(year: int) -> Panel:
    theme = year_theme(year)

    content = Text(justify="center")
    content.append("Maps to year\n\n", style="dim white")
    content.append(f"{year}", style=f"{theme['color']} underline")
    content.append(f"  {theme['label']}", style=theme["color"])
    if theme["note"]:
        content.append(f"\n\n({theme['note']})", style="dim yellow")

    title = (
        "[bold magenta]THE FUTURE[/bold magenta]"
        if year > 2025
        else "[bold]Year[/bold]"
    )
    return Panel(
        content,
        title=title,
        border_style=theme["border"],
        box=box.ROUNDED,
        padding=(1, 2),
    )


def build_events(
    year: int,
    events: list[str],
    source: str | None,
    fetching: bool,
    total: int = 0,
    shown: int = 0,
) -> Panel:
    theme = year_theme(year)
    is_future = year > 2025
    is_ancient = year < 100

    if is_future:
        panel_title = f"[bold magenta]In THE FUTURE ({year})...[/bold magenta]"
    else:
        panel_title = f"[bold]In {year}...[/bold]"

    if fetching:
        spinner = SPINNER_FRAMES[int(time.time() * 8) % len(SPINNER_FRAMES)]
        content = Text()
        content.append(f"{spinner} fetching...", style="dim yellow")
        return Panel(content, title=panel_title, border_style=theme["border"], box=box.ROUNDED, padding=(0, 2))

    if not events:
        content = Text(f"(No specific records found for year {year} — try a nearby minute)", style="dim yellow")
        return Panel(content, title=panel_title, border_style=theme["border"], box=box.ROUNDED, padding=(0, 2))

    content = Text()
    bullet_style = "magenta" if is_future else ("yellow" if is_ancient else "cyan")
    for i, event in enumerate(events):
        if i > 0:
            content.append("\n\n")
        content.append("• ", style=bullet_style)
        content.append(event, style="white")

    footer = Text()
    if source:
        footer.append(f"[via {source}]", style="dim")
    if total > 1:
        footer.append(f"  event {shown} of {total}", style="dim")

    return Panel(
        content,
        title=panel_title,
        subtitle=footer,
        border_style=theme["border"],
        box=box.ROUNDED,
        padding=(0, 2),
    )


def make_layout() -> Layout:
    layout = Layout()
    layout.split_column(
        Layout(name="header", size=3),
        Layout(name="main", ratio=1),
        Layout(name="footer"),
    )
    layout["main"].split_row(
        Layout(name="left"),
        Layout(name="right"),
    )
    return layout


# ── State ─────────────────────────────────────────────────────────────────────

class ClockState:
    def __init__(self):
        self.last_year = -1
        self.events: list[str] = []
        self.source: str | None = None
        self.total: int = 0
        self.shown: int = 0
        self.fetching = False
        self._lock = threading.Lock()

    def needs_refresh(self, year: int) -> bool:
        with self._lock:
            return year != self.last_year and not self.fetching

    def start_fetch(self, year: int):
        with self._lock:
            self.fetching = True
            self.last_year = year  # claim the year to prevent duplicate triggers

        def _fetch():
            events, source, total, shown = fetch_events(year)
            with self._lock:
                self.events = events
                self.source = source
                self.total = total
                self.shown = shown
                self.fetching = False

        threading.Thread(target=_fetch, daemon=True).start()

    def snapshot(self) -> tuple[list[str], str | None, bool, int, int]:
        with self._lock:
            return list(self.events), self.source, self.fetching, self.total, self.shown


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    console = Console()
    layout = make_layout()
    state = ClockState()

    with Live(layout, console=console, refresh_per_second=4, screen=True):
        while True:
            now = datetime.now()
            year = derive_year(now.hour, now.minute)

            if state.needs_refresh(year):
                state.start_fetch(year)

            events, source, fetching, total, shown = state.snapshot()

            layout["header"].update(build_header())
            layout["left"].update(build_clock(now))
            layout["right"].update(build_year(year))
            layout["footer"].update(build_events(year, events, source, fetching, total, shown))

            time.sleep(1)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nGoodbye!")
        sys.exit(0)
