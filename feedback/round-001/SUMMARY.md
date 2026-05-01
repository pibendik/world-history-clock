# Round 1 Expert Review — Summary

## Overview

Seven specialists reviewed the **Year Clock** (`clockapp`) — a creative PWA (+ Flutter client + FastAPI backend) that maps the current military time (`HH:MM → year YYYY`) to historical Wikidata events. The reviewers were: Senior UX Designer, Senior Software Architect, Senior Developer, Performance & Optimisation Engineer, QA Engineer, Application Security Champion, and DevOps/SRE. All seven examined the same codebase in parallel and filed independent assessments covering `server/main.py`, `server/db.py`, `server/fetcher.py`, `web/index.html`, `flutter_app/`, and `clockapp/data/epochs.py`.

---

## Cross-Cutting Themes

Five issues appeared across two or more independent reviews, signalling the highest-priority structural problems.

### Theme 1 — Zero Test Coverage
**Raised by: Senior Developer, QA, DevOps/SRE**

- **Senior Dev:** "There isn't one \[test\]. Not a single file… `derive_year` / `getYearFromTime` is the core function of the entire application… zero test coverage." The Flutter `widget_test.dart` references `MyApp` and a counter that don't exist — it would fail to compile.
- **QA:** "Zero meaningful tests… All logic — year calculation, topic filtering, era exposure tracking, dislike suppression, event buffering, SPARQL querying — is entirely untested." Proposes a full 63-test pyramid (unit/integration/E2E).
- **Ops:** No CI configuration exists. Recommends even a bare `ruff check` step as a day-one minimum.

---

### Theme 2 — Web Client Bypasses the API; localStorage and SQLite Are Separate Universes
**Raised by: Architect, Senior Dev, Performance Engineer, Security**

- **Architect:** "The web client contains a full SPARQL engine… identical logic to `fetcher.py`. All user state exists in both `localStorage` *and* the backend SQLite database, with no synchronisation mechanism."
- **Senior Dev:** "The backend's beautiful SQLite layer is functionally unused by its own web client… Either wire the web app to the API, or delete the backend. Having both is the worst outcome."
- **Performance:** "Since the Python server already persists reactions in SQLite, the localStorage copies are redundant… the server is the canonical store."
- **Security:** "The browser makes direct `fetch()` calls to `https://query.wikidata.org/sparql`… leaks the user's real IP directly. The FastAPI server proxies the request through the server, hiding the user's IP. But the browser-side fetch path bypasses this proxy."

---

### Theme 3 — Hardcoded Magic Values (Especially `_CURRENT_YEAR = 2025`)
**Raised by: Architect, Senior Dev, DevOps/SRE**

- **Architect:** "On January 1st 2026, the app will silently return no events for 2026 (treated as future) until someone edits and redeploys `main.py`." Also flags `_CACHE_TTL`, `_SPARQL_ENDPOINT`, `timeout=8`, and `DB_PATH` as hardcoded.
- **Senior Dev:** "Hard-coded. In January 2026, the server starts returning `is_future: True` for 2025. Nobody will notice until someone wonders why facts stopped showing up."
- **Ops:** "`_CURRENT_YEAR = 2025` should be `datetime.date.today().year` — a hardcoded year is a ticking maintenance bug." Also flags port `8421`, DB path, cache TTL, and CORS origins as hardcoded without config management.

---

### Theme 4 — Silent Error Swallowing
**Raised by: Senior Dev, QA**

- **Senior Dev:** "`} catch (_) {}` — That's it. That's the entire error handler for the SPARQL fetch in `fetchEventData`. Wikidata is down? Silent. Rate-limited (429)? Silent. Network timeout? Silent."
- **QA:** Identifies a concrete bug: on HTTP 500 from the server, the Flutter client `_loading` flag is never reset to `false` inside the `if (resp.statusCode == 200)` block — the loading spinner spins forever. Rates this **Critical × High likelihood**.

---

### Theme 5 — No Operational Infrastructure (Docker, CI, Pinned Deps)
**Raised by: DevOps/SRE, Security**

- **Ops:** No `Dockerfile`, no `docker-compose.yml`, no `.gitignore` exclusion of `clockapp/venv/` (platform-specific binaries are tracked in git), no CI pipeline, unpinned dependencies. "Onboarding takes 20–30 minutes of detective work instead of 2 minutes."
- **Security:** "`requirements.txt` uses unpinned names (`fastapi`, `uvicorn[standard]`, `requests`, `pydantic`). A `pip install` today may produce different results than in three months… supply-chain attack: a typosquatted or hijacked package on PyPI matching an unpinned requirement can be pulled automatically."

---

## Critical Findings (Must Fix)

1. **Buffer endpoint DoS amplification** — `server/main.py`: `/year/{year}/buffer?window=N` accepts an unbounded `window` parameter. `window=10000` triggers up to 40,002 outbound Wikidata HTTP requests in a single unauthenticated call, can exhaust server memory with a >100 MB JSON response, and risks getting the server's IP banned by Wikidata. *Security: High.*

2. **Flutter loading spinner stuck on server error** — `flutter_app/lib/main.dart` `_fetchYear`: when the server returns a non-200 status code, `_loading` is never reset to `false` (the `setState` is inside `if (resp.statusCode == 200 && mounted)`). The UI shows an infinite spinner. *QA: Critical × High likelihood.*

3. **`_CURRENT_YEAR = 2025` hardcoded** — `server/main.py` line near top: on January 1, 2026 all year 2026 events will return `is_future: true` and no facts will load. One-line fix: `datetime.date.today().year`. *Architect, Senior Dev, Ops: unanimous.*

4. **XSS via unsanitised `innerHTML`** — `web/index.html` lines ~906 and ~1020: custom topic labels are injected as `chip.innerHTML = \`🏷️ ${ct.label}...\`` and saved fact text as `<div>${s.text}</div>` without escaping. Currently self-XSS; becomes stored XSS if a browser extension touches localStorage or if topic import/export is added. *Security: Medium, QA: High.*

5. **`catch (_) {}` in `fetchEventData`** — `web/index.html` line ~790: all Wikidata failures (down, 429, timeout) are swallowed silently with no console logging, no user feedback, and no distinguishing between "no events" and "network failed". *Senior Dev: Medium.*

6. **Flutter navigation has no year bounds clamping** — `flutter_app/lib/main.dart` `_navigateYear`: can navigate to year `-1` or `2400`, sending out-of-range requests to the server which has no lower-bound validation. The web client correctly clamps with `Math.max(0, Math.min(2359, ...))`. *QA, Security.*

7. **`venv/` committed to the repository** — `clockapp/venv/` contains compiled `.so` files and pip metadata tracked in git. Platform-specific binaries in source control cause silent failures when cloned on a different OS. *Ops.*

8. **No negative result caching in `get_events_for_year`** — `server/db.py` / `server/fetcher.py`: empty Wikidata results are never stored (`if events: store_events(...)`). Ancient years with sparse data (e.g., year 3) cause repeated live Wikidata fetches on every request — a cache stampede / rate-limit trigger. *QA: Medium × High likelihood.*

---

## Top 10 Actionable Items

| # | What to fix | File(s) | Expected impact | Effort |
|---|-------------|---------|----------------|--------|
| 1 | **Cap `window` parameter + add year bounds validation** on `/buffer` and `/year/{year}` | `server/main.py` | Eliminates DoS amplification vector; prevents Wikidata IP ban | **S** |
| 2 | **Fix `_CURRENT_YEAR`** → `datetime.date.today().year` | `server/main.py` | Prevents silent fact-loading failure from Jan 1, 2026 | **S** |
| 3 | **Fix Flutter `_loading` not reset on non-200 responses** | `flutter_app/lib/main.dart` | Fixes permanently-stuck loading spinner on any server error | **S** |
| 4 | **Parallelise SPARQL queries in `fetcher.py`** using `ThreadPoolExecutor` | `server/fetcher.py` | Cuts cold-cache time-to-first-fact from ~4–8 s to ~2–4 s | **S** |
| 5 | **Sanitise `innerHTML` injection points** (custom topic chip, saved panel) with an `esc()` helper or `textContent`/`createElement` | `web/index.html` lines ~906, ~1020 | Eliminates XSS vector for user-generated content | **S** |
| 6 | **Replace `catch (_) {}` with logged error + UI feedback** | `web/index.html` line ~790 | Users see why facts aren't loading; developers get error context | **S** |
| 7 | **Pin all Python dependencies** (`pip freeze > requirements.lock`) and remove `venv/` from git | `server/requirements.txt`, `.gitignore` | Reproducible installs; closes supply-chain drift risk | **S** |
| 8 | **Write core unit tests** for `derive_year`/`getYearFromTime`, `fetch_wikidata_events` (mocked), `word_wrap`, `get_eras_for_year` | New: `clockapp/tests/` | Enables safe refactoring; catches the midnight/2359/boundary bugs | **M** |
| 9 | **Add `Dockerfile` + `docker-compose.yml`** with a named volume for SQLite and an nginx sidecar for the PWA | New files at repo root | Eliminates reproducibility, venv, DB-path, crash-recovery, and onboarding problems in one step | **M** |
| 10 | **Wire web app to FastAPI backend** (replace direct Wikidata fetch with `GET /year/{year}`; POST reactions/saves to API) | `web/index.html` | Eliminates SPARQL duplication, gives web client the server-side cache, unifies user state, removes IP privacy leak | **L** |

---

## What's Working Well

Reviewers noted several genuine strengths across the codebase:

- **Core concept and visual execution** (UX, 8/10 for visual design): the military-time-to-year metaphor is novel and the dark theme with teal accent is polished and consistent.
- **CSS theming** (Senior Dev): CSS custom properties, dark/future theme variants, `clamp()` typography, and a `future` variant that cascades cleanly through all components — described as "genuinely well-done."
- **Right-sized technology choices** (Architect): FastAPI + SQLite + vanilla JS PWA with no Kubernetes, no ORM, no build pipeline — correctly matched to the project's current scale.
- **SQLite WAL mode** (Architect, Senior Dev, Performance): `PRAGMA journal_mode=WAL` was set deliberately and correctly; it shows familiarity with SQLite's concurrency model.
- **Clean backend layering** (Architect): `fetcher.py`, `db.py`, and `main.py` have clear, testable responsibilities; the 7-day TTL cache design is correctly matched to immutable historical data.
- **Python error handling in `clock.py`** (Senior Dev): Wikidata failures return `[]`, the main loop retains the last-known fact — graceful degradation done right.
- **Dislike-to-skip feedback loop** (UX): storing dislikes in localStorage and immediately rotating to the next event is a smooth, rewarding interaction that gives users genuine agency.
- **SPARQL injection is structurally impossible** (Security): `year` is a Python `int` at the FastAPI boundary; `str(int)` cannot contain injection characters — the type system provides a hard guarantee.

---

## Round 2 Preview

**UX Designer** explicitly flagged Round 2 topics: loading states and error states (offline mode, Wikidata rate limits), Flutter client UX parity with the web app, and performance on mid-range Android devices. **Architect** has flagged that the dual SPARQL path and state-sync problems warrant a second pass once the web-client-to-API refactor is scoped. **Senior Developer** wants to revisit error boundaries and the `index.html` modularisation once tests exist — refactoring without tests is not on the table. **Performance Engineer** noted that the localStorage-to-IndexedDB migration and async SQLite (`aiosqlite`) deserve a dedicated pass once baseline benchmarks are established. **QA** intends to validate the full 63-test pyramid, focusing first on the year-calculation edge cases and the race conditions identified in §12. **Security** will revisit authentication requirements if the service is ever exposed beyond localhost, and will audit any future keyword-to-SPARQL server path for injection. **Ops/SRE** will follow up on the GitHub Actions CI pipeline and Alembic schema migration strategy once the Dockerfile exists as a foundation.
