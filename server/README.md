# YearClock API

FastAPI backend for Historieklokka — the "What Year Does It Look Like?" clock app.

## Setup

```bash
pip install -r clockapp/server/requirements.txt
```

## Run

```bash
uvicorn clockapp.server.main:app --port 8421 --reload
```

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Health check |
| GET | `/api/v1/now` | Current time → year → event (what the clock shows right now) |
| GET | `/api/v1/year/{year}` | Events + era context for a specific year |
| GET | `/api/v1/debug/wikipedia?year=N` | Raw Wikipedia events for a year (debug) |
| GET | `/api/v1/debug/sparql?year=N` | Raw SPARQL events for a year (debug only) |
| DELETE | `/api/v1/cache` | Clear the event cache (triggers warmer re-fill) |

## Architecture

- **fetcher.py** — Wikipedia `action=query&prop=revisions` with `redirects=1`; regex Events-section extraction; `_is_interesting_label` filter. No SPARQL for production fetching.
- **warmer.py** — Async background warmer; starts from current UTC hour, fills all 1440 year-slots. Runs nightly at 04:00 UTC. Also runs LLM rescore pass after warming.
- **scorer.py** — OpenAI `gpt-4o-mini` re-ranks events by historical interest. Enabled via `OPENAI_API_KEY`.
- **db.py** — SQLite tables: `event_cache` (year → events_json), `reactions`, `saved_facts`, `era_exposure`.
- **config.py** — Pydantic settings; reads from environment / `.env`.

