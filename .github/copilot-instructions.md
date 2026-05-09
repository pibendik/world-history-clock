# Historieklokka — Agent Instructions

Norwegian history clock PWA. Military time HH:MM → historical year → curated fact from that year.
Live at [historieklokka.no](https://historieklokka.no). Repo: `pibendik/world-history-clock` (the app lives in the `clockapp/` subdirectory).

## Build & Test

```bash
# Tests (run from clockapp/)
source venv/bin/activate
python -m pytest tests/ -q          # 50 tests, should all pass

# Local dev
docker compose up --build           # http://localhost:8421

# Deploy to production
./deploy.sh root@77.42.120.231
./deploy.sh root@77.42.120.231 --clear-cache   # also flushes SQLite event cache
```

All env vars are prefixed `YEARCLOCK_`. See [`.env.example`](.env.example). Exception: `OPENAI_API_KEY` (no prefix).

## Architecture

**Stack:** FastAPI + SQLite backend, single-file PWA frontend (`web/index.html`), Caddy reverse proxy, Docker Compose. No framework on the frontend — plain JS.

**Bilingual deployment** via `YEARCLOCK_LANG` env var:
- `no` → historieklokka.no (Norwegian, current deployment)
- `en` → future English domain

Language affects: LLM scorer prompt, data files loaded, epoch names returned by `/api/v1/config`.

**Data files** — language variants follow the pattern `{base}.{lang}.json`:
- `data/epochs.json` / `data/epochs.no.json` — 51 eras with date ranges
- `data/era_context.json` / `data/era_context.no.json` — ~70 era context sentences
- `data/future_events.json` / `data/future_events.no.json` — curated 2026–2359 events

`data/epochs.py` is a language-aware loader (not data itself). Use `_lang_file("filename.json")` to load the correct language variant.

**Content pipeline:**
1. Wikipedia fetch (`fetcher.py`) — `action=query&prop=revisions`, events section via regex
2. Boring-pattern filter — sports seasons, Q-codes, Olympics participation, etc.
3. LLM scoring (`scorer.py`, `gpt-4o-mini`) — selects 3–5 best events, rewrites as vivid prose
4. Era-context fallback — if no events found, shows a context sentence (logged as WARNING)
5. Cache warmer (`warmer.py`) — runs nightly 04:00 UTC, starts from current hour

**Key API endpoints:**
- `GET /api/v1/now` — what the clock shows right now
- `GET /api/v1/year/{year}` — data for a specific year
- `GET /api/v1/config` — frontend config (lang + epoch list)
- `GET /api/v1/debug/wikipedia?year=N` — raw Wikipedia events (debug)

## Norwegian Language Requirements

Event text and UI **must** sound like genuine Oslo/Østlandet bokmål — not translated English. The LLM scorer prompt (`_SYSTEM_PROMPT_NO` in `scorer.py`) encodes these rules with negative examples. Key principles:

- Prefer compound words: `sjøslag`, `kongemord`, `folkevandring`
- Use particles: `da`, `jo`, `vel`
- Verb-early sentences: «Da kongen falt, ble riket delt.»
- `man` not `du` for generic statements
- Avoid English-calque constructions (see negative examples in `scorer.py`)

Narrator voice: «a wise uncle giving a talk — engaged, slightly dry, not solemn».

## Common Pitfalls

- **`YEARCLOCK_LANG` alias**: config uses `validation_alias="YEARCLOCK_LANG"` (not env_prefix) because pydantic-settings would otherwise produce `YEARCLOCK_YEARCLOCK_LANG`.
- **Router vs app**: all `/api/v1/*` routes must be registered on `router` (prefix `/api/v1`), not on `app` directly.
- **Scorer prompt variable**: the prompt is `_SYSTEM_PROMPT_NO` / `_SYSTEM_PROMPT_EN` — not `_SYSTEM_PROMPT`. Tests mock the LLM, so prompt changes don't break them, but test imports must reference the correct names.
- **Future events cache**: `_load_future_events()` in `epochs.py` caches by lang and invalidates on lang change — important for tests that switch lang.
- **Wikipedia early years**: articles for years before ~800 are often titled "N AD" and redirect. The fetcher handles `redirects=1` — don't remove it.

## Key Files

| File | Purpose |
|------|---------|
| `server/main.py` | All API routes |
| `server/scorer.py` | LLM prompt + scoring logic |
| `server/fetcher.py` | Wikipedia fetch + boring-pattern filter |
| `data/epochs.py` | Language-aware data loader |
| `data/era_context.no.json` | Norwegian era context (review before editing — arch-Norwegian style) |
| `web/index.html` | Entire frontend (~1200 lines) |
| `deploy.sh` | Production deploy script |
| `SERVER-SETUP.md` | Server provisioning guide |
