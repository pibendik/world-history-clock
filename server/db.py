"""SQLite database layer for YearClock. DB stored at ~/.clockapp/yearclock.db"""

import json
import sqlite3
import time

from clockapp.server.config import settings

_DB_PATH = settings.db_path
_CACHE_TTL = settings.cache_ttl_days * 24 * 3600


def get_db() -> sqlite3.Connection:
    _DB_PATH.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(_DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS event_cache (
            year INTEGER PRIMARY KEY,
            events_json TEXT NOT NULL,
            fetched_at REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS reactions (
            key TEXT PRIMARY KEY,
            year INTEGER NOT NULL,
            text TEXT NOT NULL,
            source TEXT,
            reaction TEXT NOT NULL,
            created_at REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS saved_facts (
            key TEXT PRIMARY KEY,
            year INTEGER NOT NULL,
            text TEXT NOT NULL,
            source TEXT,
            saved_at REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS era_exposure (
            era_name TEXT PRIMARY KEY,
            shown_count INTEGER NOT NULL DEFAULT 0
        );
    """)
    conn.commit()
    return conn


def get_cached_events(year: int) -> list[dict] | None:
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT events_json, fetched_at FROM event_cache WHERE year = ?", (year,)
        ).fetchone()
        if row is None:
            return None
        if time.time() - row["fetched_at"] > _CACHE_TTL:
            return None
        return json.loads(row["events_json"])
    finally:
        conn.close()


def store_events(year: int, events: list[dict]) -> None:
    conn = get_db()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO event_cache (year, events_json, fetched_at) VALUES (?, ?, ?)",
            (year, json.dumps(events, ensure_ascii=False), time.time()),
        )
        conn.commit()
    finally:
        conn.close()


def get_all_cached_years() -> list[tuple[int, list[dict]]]:
    """Return (year, events) for all non-expired cache entries."""
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT year, events_json FROM event_cache WHERE fetched_at > ?",
            (time.time() - _CACHE_TTL,),
        ).fetchall()
        return [(r["year"], json.loads(r["events_json"])) for r in rows]
    finally:
        conn.close()



    conn = get_db()
    try:
        rows = conn.execute("SELECT * FROM reactions").fetchall()
        return {r["key"]: dict(r) for r in rows}
    finally:
        conn.close()


def set_reaction(year: int, text: str, source: str | None, reaction: str) -> None:
    key = f"{year}::{text}"
    conn = get_db()
    try:
        conn.execute(
            """INSERT OR REPLACE INTO reactions (key, year, text, source, reaction, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (key, year, text, source, reaction, time.time()),
        )
        conn.commit()
    finally:
        conn.close()


def get_saved() -> list[dict]:
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT * FROM saved_facts ORDER BY saved_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def save_fact(year: int, text: str, source: str | None) -> None:
    key = f"{year}::{text}"
    conn = get_db()
    try:
        conn.execute(
            """INSERT OR IGNORE INTO saved_facts (key, year, text, source, saved_at)
               VALUES (?, ?, ?, ?, ?)""",
            (key, year, text, source, time.time()),
        )
        conn.commit()
    finally:
        conn.close()


def remove_saved(key: str) -> None:
    conn = get_db()
    try:
        conn.execute("DELETE FROM saved_facts WHERE key = ?", (key,))
        conn.commit()
    finally:
        conn.close()


def get_era_exposure() -> dict[str, int]:
    conn = get_db()
    try:
        rows = conn.execute("SELECT era_name, shown_count FROM era_exposure").fetchall()
        return {r["era_name"]: r["shown_count"] for r in rows}
    finally:
        conn.close()


def increment_era_exposure(era_name: str) -> None:
    conn = get_db()
    try:
        conn.execute(
            """INSERT INTO era_exposure (era_name, shown_count) VALUES (?, 1)
               ON CONFLICT(era_name) DO UPDATE SET shown_count = shown_count + 1""",
            (era_name,),
        )
        conn.commit()
    finally:
        conn.close()
