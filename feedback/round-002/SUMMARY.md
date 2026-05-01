# Round 2 Expert Review — Summary

Seven specialists reviewed the **Year Clock** (`clockapp`) for a second time. Reviewers: Senior UX Designer, Senior Software Architect, Senior Developer, Performance & Optimisation Engineer, QA Engineer, Application Security Champion, and DevOps/SRE.

---

## What Changed from Round 1

Round 1 was a **diagnostic pass**: reviewers named problems, measured gaps, and catalogued risks. The tone was exploratory and at times alarmed — "That's it. That's the entire error handler." — because the reviewers were encountering the codebase cold and finding fragile patterns at every layer.

Round 2 is a **prescriptive pass**: every section in every report contains exact, runnable code. The shift in depth is significant. Where Round 1 said *"cap the `window` parameter"*, Round 2 delivers the exact FastAPI `Path()` and `Query()` decorator arguments, the validated constants, and an explanation of why `ge`/`le` constraints surface in the OpenAPI schema. Where Round 1 said *"write tests"*, Round 2 delivers 63 test cases with fixtures, parametrised edge-cases, and a confession that one of those tests immediately found a real bug in production code (the `startswith("Q")` filter that silently drops events whose labels begin with an uppercase Q but are not Q-codes — e.g. "Queen's coronation ceremony").

**Tone shift:** Round 1 reviewers were reacting to what they found. Round 2 reviewers are in agreement about what to build. The Architect, Performance engineer, and Ops/SRE are now clearly coordinating toward the same infrastructure vision (Docker → Pydantic settings → versioned API → wired web client) even though they filed independent reviews. The QA engineer moved from "here is what I would test" to "here is the test file, copy it in." The Security reviewer moved from "this is a problem" to "add this middleware, these exact headers, this CORS function."

The Senior Developer's tone did not soften: Round 2 opened with "This round is about the actual lines of code that need to change — not impressions, not vibes."

**Depth shift by reviewer:**

| Reviewer | Round 1 depth | Round 2 depth |
|---|---|---|
| Architect | Identified dual SPARQL path, state-sync flaw, API versioning need | Full target architecture diagram; migration code; async buffer redesign; composite key schema |
| Senior Dev | Named 8 code-level problems | Exact before/after diffs for 6 fixes; extracted `sparql.py` shared module; full test plan |
| Performance | Measured latency budgets, identified serial SPARQL | `ThreadPoolExecutor` implementation; persistent `threading.local` connection; Flutter `http.Client` reuse; UNION query option |
| QA | Proposed 63-test pyramid | Wrote the test files: `test_epochs.py`, `test_fetcher.py`, `test_year_calculation.py`, Jest `YearCache` suite; found Q-code false-positive bug |
| Security | Named XSS points, DoS vector, unpinned deps | `sanitise()` + `sanitiseUrl()` helpers; `SecurityHeadersMiddleware`; CORS tightening; `slowapi` rate limiting; Pydantic body validators |
| Ops/SRE | Declared no Dockerfile, no CI, no `.gitignore` | Delivered `Dockerfile` (multi-stage), `docker-compose.yml`, `config.py` (Pydantic Settings), full GitHub Actions CI pipeline, SLO definitions, structured JSON logging |
| UX | Named tap target failures, missing onboarding, contrast issues | Full CSS fixes for every failing element; three-step tooltip onboarding spec; live/browse mode visual design; complete ARIA label table; progressive disclosure strategy |

---

## Cross-Cutting Themes (Round 2)

### Theme 1 — Wire the Web App to the API
**Raised by: Architect, Senior Dev, Security, Performance, Ops/SRE**

Every reviewer who touched the server/client boundary independently arrived at the same conclusion: the web app bypassing the FastAPI backend is the single most expensive structural problem in the codebase, and all other improvements compound once it is fixed. The Architect calls it "the single most important change to make first" and quantifies the refactor as "one afternoon: replace ~120 lines of SPARQL boilerplate in `index.html` with 15 lines of `fetch()` calls." The Performance engineer notes that fixing this eliminates localStorage redundancy and routes the web client through the 7-day SQLite cache it currently ignores. Security notes it removes the user IP privacy leak (direct browser-to-Wikidata connection). Ops/SRE notes it removes the CORS wildcard justification.

**Round 1 status: identified but unresolved. Round 2: full solution code provided.**

### Theme 2 — Tests, Tests, Tests
**Raised by: QA, Senior Dev, Ops/SRE**

Zero meaningful test coverage persists from Round 1. Round 2 does not merely re-raise this — it delivers executable test code. QA wrote the full pytest suite (`test_epochs.py`, `test_fetcher.py`, `test_year_calculation.py`) and a Jest suite for `YearCache`. Senior Dev wrote `test_derive_year.py` and `test_get_eras_for_year.py`. Ops/SRE provides a GitHub Actions CI pipeline that runs `pytest` and `ruff` on every push. QA explicitly noted that writing one of these tests immediately surfaced a production bug (the Q-code regex false-positive on labels starting with "Q" that aren't Q-codes).

**Round 1 status: identified as highest-priority gap. Round 2: test files written and ready to run.**

### Theme 3 — Configuration Must Leave the Source Code
**Raised by: Architect, Senior Dev, Security, Ops/SRE**

`_CURRENT_YEAR = 2025`, `_SPARQL_ENDPOINT`, `DB_PATH`, `_CACHE_TTL`, `allow_origins=["*"]`, port `8421` — all hardcoded across `main.py`, `db.py`, and `fetcher.py`. This theme spans from a time-bomb (the year constant fails silently on 1 January 2026) to a security concern (CORS wildcard cannot be tightened without touching source). The Architect and Ops/SRE independently designed the same solution: a `clockapp/server/config.py` using `pydantic-settings.BaseSettings`, reading from `.env` with `YEARCLOCK_*` prefixed environment variables. Both even agree on the exact field names. The Senior Dev fixes the year constant directly while recommending `pyproject.toml` for proper package structure.

**Round 1 status: flagged as three separate issues. Round 2: converged on one unified `config.py` solution.**

### Theme 4 — Replace `catch (_) {}` with Classified Error Handling
**Raised by: Senior Dev, UX, QA**

The silent catch in `fetchEventData` was identified in Round 1. Round 2 produced concrete solutions: the Senior Dev proposes a layered strategy (log all → classify at call site → set app state per error type → schedule retry for 429). The UX designer specifies the exact UI for each state (offline card with last-known fact, rate-limit message, Wikidata error banner, empty-year structured card with adjacent-year navigation). QA's Flutter test suite includes the specific regression for the Flutter `_loading` spinner stuck on non-200 responses — the test would catch the bug that Round 1 rated Critical.

**Round 1 status: identified as critical bug (Flutter) and medium bug (web). Round 2: full error classification strategy + UI specifications.**

### Theme 5 — Operational Infrastructure (Docker, CI, Pinned Deps)
**Raised by: Ops/SRE, Security, Senior Dev**

Round 1 established that none of this exists. Round 2 delivers it: a multi-stage Dockerfile with non-root user, a `docker-compose.yml` with nginx sidecar and named SQLite volume, a four-job GitHub Actions workflow (lint → test → docker build → HTML validate), `requirements.in` with `pip-compile` producing hash-verified `requirements.txt`, and `.env.example`. The Security reviewer reinforces this with `pip-audit` integration and a Dependabot configuration. Senior Dev adds `pyproject.toml` to fix the `sys.path.insert` hack that currently exists in production code.

**Round 1 status: flagged as onboarding/reproducibility gap. Round 2: complete working infrastructure files ready to commit.**

---

## Consensus Prescriptions

Items where **three or more experts independently recommended the same concrete fix**:

### 1. Wire `index.html` to `GET /api/v1/year/{year}` and delete the SPARQL block
**Experts: Architect, Senior Developer, Security, Performance, Ops/SRE (5/7)**

Replace `fetchEventData()`'s ~120 lines of SPARQL construction with a single `fetch()` call to the FastAPI backend. The Architect provides the exact replacement function (15 lines). Security notes this eliminates the direct-to-Wikidata IP leak. Performance notes the web client will get the 7-day SQLite cache for free. Ops/SRE notes CORS can be tightened once there is one origin. Senior Dev calls having both implementations "the worst outcome."

### 2. Fix `_CURRENT_YEAR = 2025` → `datetime.date.today().year`
**Experts: Architect, Senior Developer, Security, Ops/SRE, UX (5/7)**

A one-line fix that prevents a silent failure on 1 January 2026 where the app stops showing facts for all years above 2025. All five reviewers include the exact fix (Architect specifies the module-level constant; Security uses it in the `Path()` bounds definition; UX references it in the future-state card copy calculation; Ops wraps it in `config.py`). The unanimous urgency is notable: this is the most-agreed-upon single change in the entire review.

### 3. Add `Dockerfile` + `docker-compose.yml` with named SQLite volume
**Experts: Ops/SRE, Security, Senior Dev, Architect (4/7)**

Ops/SRE delivers the complete files. Security reinforces the non-root user requirement and `.env` secret management. Architect's target architecture diagram includes nginx as an optional sidecar. Senior Dev's `pyproject.toml` fix is a prerequisite for the `pip install -e .` step inside the container. All four agree the container must use `--workers 1` for SQLite WAL correctness.

### 4. Add a `Pydantic Settings` config layer; remove all hardcoded constants
**Experts: Architect, Ops/SRE, Security, Senior Dev (4/7)**

Both Architect and Ops/SRE independently wrote nearly identical `config.py` files using `pydantic-settings.BaseSettings` with `YEARCLOCK_*` environment variable prefixes. Security uses the same settings pattern for CORS origins. Senior Dev's angle is that `YEARCLOCK_DB_PATH=:memory:` enables isolated test runs with zero cleanup code. The consensus is not just "externalise config" but specifically "use `pydantic-settings`" — this level of tool convergence across independent reviewers is remarkable.

### 5. Sanitise all `innerHTML` injection points using a `sanitise()` / `esc()` helper
**Experts: Security, Senior Dev, UX (3/7)**

Security provides the exact `sanitise()` function using `el.textContent = str; return el.innerHTML` (browser-native escaping, no regex). The fix targets four specific line numbers (704, 906, 1013–1023, 1070–1077). Senior Dev flags the `chip.innerHTML` pattern as a second-order concern once tests exist. UX independently flags the same issue when proposing the `chip-remove` button redesign — noting that the label injection must be escaped. The current risk is self-XSS; the future risk is stored XSS if topic import/export is ever added.

### 6. Cap `window` to max 5; add `Path(ge=0, le=2359)` on all year parameters
**Experts: Security, Architect, Senior Dev (3/7)**

Security provides the exact FastAPI decorator syntax. Architect redesigns the buffer endpoint as fire-and-forget with background tasks, making the window cap a prerequisite. Senior Dev flags the missing lower-bound validation for Flutter's year navigation (can navigate to year -1). The worst-case amplification drops from 40,002 Wikidata requests to 11 with a `max_window=5` cap.

### 7. Parallelise SPARQL queries in `fetcher.py` using `ThreadPoolExecutor`
**Experts: Performance, Architect, Senior Dev (3/7)**

Performance provides the exact `ThreadPoolExecutor(max_workers=2)` implementation with measurable targets (cold-cache time halved from sum-of-both to max-of-both). Architect's buffer redesign uses the same parallelism pattern with `httpx.AsyncClient`. Senior Dev's test plan includes the mock-based test that validates parallel invocation. All three note this is the highest-ROI single-line performance change.

---

## Contested Ground

### Flutter: Delete it vs. Keep it
**Senior Dev vs. Architect + UX**

The Senior Developer is sceptical of the Flutter client throughout Round 2. The `http.Client` reuse fix, the `_loading` spinner bug, and the missing year bounds clamping are treated as evidence that the Flutter client is an under-maintained secondary surface. Senior Dev does not explicitly recommend deletion (that was Round 1 language), but Round 2's treatment of Flutter is minimal — the focus is on wiring *everything* to the API so at least duplication is eliminated.

The Architect explicitly includes Flutter in the target architecture diagram as a first-class client, equal to the web PWA. The UX designer's Round 2 review focuses entirely on the web PWA but the Round 1 preview mentioned Flutter UX parity as a Round 2 topic — the UX designer appears to have scoped it out, possibly signalling that parity is too far off to specify in detail.

**Resolution path:** Wire Flutter to the API first (it already calls `$kBaseUrl/year/$year`; it just needs the `http.Client` reuse fix and session token header). Defer the "delete Flutter" question until the API is the single source of truth — at that point Flutter has zero marginal maintenance cost for the data layer.

### localStorage: Eliminate it vs. Migrate to IndexedDB vs. Keep It
**Architect vs. Performance Engineer**

The Architect proposes eliminating localStorage entirely for reactions and saved facts: use the FastAPI backend as the authoritative store, with localStorage only as a write-through cache for the session token. Provides migration code that bulk-uploads existing saves on first upgrade.

The Performance engineer proposes a threshold-based migration: stay on localStorage until reaction JSON exceeds 50 KB (~250 entries) or saved facts exceed 20 KB (~100 entries), then migrate to `idb-keyval` (< 1 KB gzip). Notes that the localStorage copies are "purely a client-side cache" and agrees the cleanest long-term solution is to eliminate them — but argues that migration is premature until the server API is actually wired up.

Security sides with the Architect: any localStorage state that duplicates server state is a synchronisation risk and a privacy surface.

**Resolution path:** Performance engineer's position is a pragmatic sequencing argument, not a permanent disagreement. After wiring the web app to the API (Theme 1), the localStorage elimination becomes straightforward and the Performance engineer's threshold concern becomes moot.

### SPARQL: UNION Query vs. Parallel Threads
**Performance Engineer (both options presented)**

The Performance engineer presents two approaches to eliminating the serial SPARQL bottleneck: `ThreadPoolExecutor` parallelism (§1, recommended as the safer first step) and a single UNION query (§6, presented as an option). The UNION approach reduces one HTTP connection to Wikidata but may be slower on years with high event density (e.g. 1969) due to Wikidata's query planner. The parallel approach is simpler and safer. The Architect also recommends the parallel approach with `httpx.AsyncClient` for the buffer redesign.

**Recommendation:** Implement `ThreadPoolExecutor` first. Benchmark against a UNION query on 10 high-density years before committing to the UNION.

### Era Stats Panel: Cut it vs. Keep It
**UX Designer vs. Everyone Else**

The UX designer is the only reviewer who explicitly recommends removing a feature. The era exposure stats panel ("📊 Era stats") is described as "a developer dashboard masquerading as a user feature" — the vocabulary is opaque (`Score: 1.33`), there is no action to take on the data, and it competes with the core discovery loop. The proposed replacement: a contextual invitation ("You've rarely explored the Viking Age — want to?") inside the year card itself.

No other reviewer addresses the era stats panel. The Architect's target architecture retains `era_exposure` as a SQLite table. The backend team implicitly treats the balancing algorithm as a valuable feature.

**Resolution path:** The UX designer's critique is about the *presentation*, not the underlying algorithm. Keeping the algorithm while hiding the raw panel behind a developer toggle (or removing the panel entirely in favour of the contextual nudge) would satisfy the UX concern without the backend disagreement.

### Pydantic `response_model=` vs. gRPC for Type Safety
**Architect vs. (nobody — but it's worth noting)**

The Architect explicitly rules out gRPC ("Stay on REST. Add `response_model=` annotations in FastAPI to get the type safety benefit of gRPC without the complexity") but notes the conditions under which gRPC would be worth it: server streaming, >50 RPC types, or multiple language clients sharing a `.proto` contract. No other reviewer raises gRPC at all, so this is the Architect preemptively closing a question that was hinted at in Round 1.

---

## The "First Sprint" — Top 10 Actions

Ordered by: (severity of unfixed risk) × (consensus strength) ÷ (estimated effort). Items that unblock other items are ranked higher.

| # | Action | Files | Effort | Expert consensus |
|---|--------|-------|--------|-----------------|
| 1 | **Fix `_CURRENT_YEAR = 2025`** → `datetime.date.today().year` | `server/main.py` | **XS** (1 line) | Architect, Senior Dev, Security, Ops, UX (5/7) |
| 2 | **Cap `window` ≤ 5; add `Path(ge=0, le=2359)` to all year routes** | `server/main.py` | **S** (10 lines) | Security, Architect, Senior Dev (3/7) |
| 3 | **Add `sanitise()` + `sanitiseUrl()` helpers; apply to all 4 `innerHTML` injection points** | `web/index.html` | **S** (30 lines) | Security, Senior Dev, UX (3/7) |
| 4 | **Replace `catch (_) {}` with classified error handler + UI states** | `web/index.html` | **S** (40 lines) | Senior Dev, UX, QA (3/7) |
| 5 | **Cache empty Wikidata results** (`store_events` unconditionally in `fetcher.py`) | `server/fetcher.py` | **XS** (2 lines) | Senior Dev, QA (2/7, but blocks cache stampede) |
| 6 | **Parallelise SPARQL queries** with `ThreadPoolExecutor(max_workers=2)` | `server/fetcher.py` | **S** (10 lines) | Performance, Architect, Senior Dev (3/7) |
| 7 | **Create `config.py`** (Pydantic Settings); replace all hardcoded constants | `server/config.py`, `main.py`, `db.py`, `fetcher.py` | **M** (1 new file + 4 diffs) | Architect, Ops, Security, Senior Dev (4/7) |
| 8 | **Add `Dockerfile` + `docker-compose.yml`** with named SQLite volume, nginx sidecar, non-root user | New `Dockerfile`, `docker-compose.yml`, `deploy/nginx/yearclock.conf` | **M** (files provided in ops review) | Ops, Security, Architect (3/7) |
| 9 | **Add GitHub Actions CI** (ruff lint → pytest → docker build) | `.github/workflows/ci.yml` | **M** (file provided in ops review) | Ops, QA, Senior Dev (3/7) |
| 10 | **Wire `index.html` to `GET /api/v1/year/{year}`** (replace 120-line SPARQL block with 15-line `fetch()`) | `web/index.html` | **L** (one afternoon) | Architect, Senior Dev, Security, Performance, Ops (5/7) |

> **Note on ordering:** Items 1–6 are hardening changes that reduce risk on the currently-deployed codebase with minimal surface area. Items 7–9 are infrastructure prerequisites that make Item 10 durable. Item 10 is last not because it is least important — it is the *most* important strategically — but because it is safest to do after the config layer, CI, and tests exist to validate the change.

---

## Round 3 Preview

**What's still unresolved:**

1. **State synchronisation across devices.** The Architect's session-token + server-authoritative model (§2 of the architecture review) is designed but not built. Until the web app is wired to the API (Sprint Item 10), there is no foundation for cross-device sync. Round 3 should validate the session token design, the bulk-migration path for existing localStorage data, and the conflict-resolution strategy.

2. **Flutter UX parity.** The UX designer scoped Flutter out of Round 2. The Flutter client is missing: error state UI, offline mode, browse vs. live mode differentiation, proper tap targets (the same issues the web app has). Round 3 should either audit Flutter against the UX spec delivered in Round 2 for the web, or make a deliberate decision to archive it.

3. **The Q-code regex false-positive.** QA's Round 2 test (`test_q_code_lowercase_not_excluded`) documented a real production bug: `startswith("Q")` silently drops event labels like "Queen's coronation ceremony." The fix (`^Q\d+$` regex) is a one-liner but it has data implications — events that were previously filtered out will now appear. Round 3 should verify the fix against a sample of live Wikidata responses and check whether the 15-character minimum label length filter is still the right threshold.

4. **Accessibility validation.** The UX designer provided a complete ARIA label table and keyboard navigation specification. None of this has been implemented or tested with a screen reader. Round 3 should include an axe-core automated scan and a manual VoiceOver/TalkBack pass.

5. **CSP header and `app.js` extraction.** Security provided a full Content-Security-Policy specification, but it requires moving the inline `<script>` block to an external `app.js` file to enable `script-src 'self'`. This is a medium-effort refactor that was deferred from the current sprint. Round 3 should complete this — it is a prerequisite for meaningful XSS blast-radius reduction.

6. **Cache warming strategy.** The Performance engineer outlined a 1 req/60 s startup warm-up targeting 99% cache hit rate after 48 hours. This has measurable targets (`< 40 hours` to full cache) but no implementation yet. Round 3 should either build `cache_warmer.py` or decide that client-side ±2 buffering is sufficient.

7. **Era stats feature decision.** The UX designer recommends replacing the panel with a contextual nudge. No implementation exists. A Round 3 UX pass should include a prototype of the "You've rarely explored the Viking Age — want to?" card treatment and validate it against the current era exposure algorithm output.
