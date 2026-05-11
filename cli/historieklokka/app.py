#!/usr/bin/env python3
"""Historieklokka — historieklokkа i terminalen.

Viser hva klokken ser ut som som et historisk årstall og en hendelse fra det året,
hentet fra historieklokka.no.

Bruk: historieklokka [--api URL]
"""

import argparse
import sys
import threading
import time
from datetime import datetime

import requests
from rich import box
from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.text import Text

DEFAULT_API = "https://historieklokka.no/api/v1"
SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
_CURRENT_YEAR = datetime.now().year


# ── Data ──────────────────────────────────────────────────────────────────────

def derive_year(now: datetime) -> int:
    return now.hour * 100 + now.minute


def fetch_year_data(year: int, api_base: str) -> dict | None:
    try:
        r = requests.get(f"{api_base}/year/{year}", timeout=15)
        r.raise_for_status()
        return r.json()
    except Exception:
        return None


# ── Theming ───────────────────────────────────────────────────────────────────

def _theme(year: int) -> dict:
    if year > _CURRENT_YEAR:
        return {"color": "bold magenta", "border": "magenta", "bullet": "magenta"}
    if year < 100:
        return {"color": "bold yellow", "border": "yellow", "bullet": "yellow"}
    return {"color": "bold cyan", "border": "cyan", "bullet": "cyan"}


# ── Panels ────────────────────────────────────────────────────────────────────

def build_header() -> Panel:
    t = Text("Historieklokka", justify="center")
    t.stylize("bold white")
    return Panel(t, style="on navy_blue", border_style="bright_blue", box=box.HEAVY, padding=(0, 2))


def build_clock(now: datetime) -> Panel:
    content = Text(justify="center")
    content.append(now.strftime("%H:%M:%S") + "\n", style="bold bright_green")
    content.append(now.strftime("%B %-d, %Y"), style="dim white")
    return Panel(
        content,
        title="[bold green]Clock[/bold green]",
        border_style="green",
        box=box.ROUNDED,
        padding=(1, 2),
    )


def build_year_panel(year: int, data: "dict | None") -> Panel:
    theme = _theme(year)
    content = Text(justify="center")
    content.append(str(year), style=f"{theme['color']} underline")
    if year > _CURRENT_YEAR:
        content.append("  FUTURE", style=theme["color"])
    elif year < 100:
        content.append("  ANTIQUITY", style=theme["color"])

    if data:
        era = data.get("era_display") or ""
        if not era and data.get("eras"):
            era = data["eras"][0].get("name", "")
        if era:
            content.append(f"\n\n{era}", style="dim white")

    title = "[bold magenta]Future[/bold magenta]" if year > _CURRENT_YEAR else "[bold]Year[/bold]"
    return Panel(content, title=title, border_style=theme["border"], box=box.ROUNDED, padding=(1, 2))


def build_event_panel(year: int, data: "dict | None", fetching: bool, error: bool) -> Panel:
    theme = _theme(year)
    title = (
        f"[bold magenta]In the future ({year})...[/bold magenta]"
        if year > _CURRENT_YEAR
        else f"[bold]In {year}...[/bold]"
    )

    if fetching:
        spinner = SPINNER_FRAMES[int(time.time() * 8) % len(SPINNER_FRAMES)]
        return Panel(
            Text(f"{spinner} fetching from historieklokka.no…", style="dim yellow"),
            title=title, border_style=theme["border"], box=box.ROUNDED, padding=(1, 2),
        )

    if error or data is None:
        return Panel(
            Text("Could not reach historieklokka.no — check your network connection.", style="dim red"),
            title=title, border_style="red", box=box.ROUNDED, padding=(1, 2),
        )

    events = data.get("future_events") if year > _CURRENT_YEAR else data.get("events") or []
    event_text = events[0]["text"] if events else data.get("context", "")

    if not event_text:
        return Panel(
            Text(f"(No events found for year {year})", style="dim yellow"),
            title=title, border_style=theme["border"], box=box.ROUNDED, padding=(1, 2),
        )

    content = Text()
    content.append("• ", style=theme["bullet"])
    content.append(event_text, style="white")

    source_label = ""
    if events and "original" in events[0]:
        source_label = "Wikipedia"
    elif year > _CURRENT_YEAR:
        source_label = "curated"

    return Panel(
        content,
        title=title,
        subtitle=Text(f"[via {source_label}]", style="dim") if source_label else None,
        border_style=theme["border"],
        box=box.ROUNDED,
        padding=(1, 2),
    )


# ── State ─────────────────────────────────────────────────────────────────────

class ClockState:
    def __init__(self, api_base: str):
        self._api_base = api_base
        self._last_year = -1
        self._data: "dict | None" = None
        self._fetching = False
        self._error = False
        self._lock = threading.Lock()

    def needs_refresh(self, year: int) -> bool:
        with self._lock:
            return year != self._last_year and not self._fetching

    def start_fetch(self, year: int) -> None:
        with self._lock:
            self._fetching = True
            self._last_year = year

        def _work():
            result = fetch_year_data(year, self._api_base)
            with self._lock:
                self._data = result
                self._fetching = False
                self._error = result is None

        threading.Thread(target=_work, daemon=True).start()

    def snapshot(self) -> "tuple[dict | None, bool, bool]":
        with self._lock:
            return self._data, self._fetching, self._error


# ── Layout ────────────────────────────────────────────────────────────────────

def make_layout() -> Layout:
    layout = Layout()
    layout.split_column(
        Layout(name="header", size=3),
        Layout(name="top", size=8),
        Layout(name="event", ratio=1),
    )
    layout["top"].split_row(Layout(name="clock"), Layout(name="year"))
    return layout


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Historieklokka — history clock in the terminal")
    parser.add_argument(
        "--api",
        default=DEFAULT_API,
        metavar="URL",
        help=f"API base URL (default: {DEFAULT_API})",
    )
    args = parser.parse_args()

    console = Console()
    layout = make_layout()
    state = ClockState(api_base=args.api)

    with Live(layout, console=console, refresh_per_second=4, screen=True):
        while True:
            now = datetime.now()
            year = derive_year(now)

            if state.needs_refresh(year):
                state.start_fetch(year)

            data, fetching, error = state.snapshot()

            layout["header"].update(build_header())
            layout["clock"].update(build_clock(now))
            layout["year"].update(build_year_panel(year, data))
            layout["event"].update(build_event_panel(year, data, fetching, error))

            time.sleep(0.25)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nGoodbye!")
        sys.exit(0)
