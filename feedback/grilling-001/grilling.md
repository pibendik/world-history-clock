# Grilling Session 001 — Year Clock Architecture & Vision

**Date:** 2026-05-08  
**Format:** Socratic interview — questions asked one at a time, codebase explored before asking where answerable from code.

---

## Purpose

The developer described the codebase as "spaghetti I don't understand" after a period of rapid feature development. This session grilled the owner on: tech stack, user experience, goals, code flow, the command-line vision, the proposed `/now` API endpoint, and the physical clock dream. The goal was to reach shared understanding and a clear prioritised action list.

---

## Decisions Made

### 1. What the app is for

- **Primary:** Daily companion — something you glance at throughout the day like a desk clock
- **Secondary:** First-glance curiosity — fun at first sight, even if you never return
- **Future:** Physical installation — a library or school display built by "the artsy engineer" (a friend who is both artist and electronic engineer)
- **Intended audience:** Curious people who get the concept instantly. ~50% of the 10 people shown it understood within one second. The other 50% needed explanation. The app should cater to those who get it — they are the intended audience.

### 2. CLI version — plan

The dependency chain is fixed:

```
/api/v1/now endpoint  ← everything else depends on this
       ↓
  curl one-liner (document in README)
       ↓
  pip package (yearclock CLI)
       ↓
  brew formula / AUR package
       ↓
  live terminal clock (multi-line Rich display)
```

The developer wants to eventually publish a proper installable package (`pip install yearclock`) and a live multi-line terminal clock. Linux users will likely prefer the raw `/now` endpoint for `.bashrc` customisation. Both are valid target uses.

### 3. `/api/v1/now` endpoint — design spec

**Does not exist yet. Most important thing to build.**

Response shape (flat JSON — no nesting, usable with `jq`):

```json
{
  "time": "11:01",
  "year": 1101,
  "event": "The Crusaders establish the County of Tripoli...",
  "context": "Most people in Europe lived in small farming villages...",
  "era": "High Middle Ages",
  "ongoing": "The Crusades",
  "source": "Wikidata",
  "source_url": "https://www.wikidata.org/wiki/Special:Search?search=1101"
}
```

**Key design decisions:**
- `era` and `ongoing` are **separate fields** (more flexibility for consumers)
- `source_url` is nullable (future events / era context have no URL)
- Uses **UTC** by default; optional `?tz=Europe/Oslo` parameter
- **Variety via date-seeded rotation:** day-of-year `%` number-of-events selects which event to return. No server-side per-user tracking. Varies daily for the 09:00 breakfast user without any state.
- Future years (21:xx → 2100+) return `future_events` (sci-fi + astronomy), not empty
- No character limits — let consumers truncate. Can add `?max_chars=N` later.

**Mapping to existing data:**

| Field | Source | Status |
|---|---|---|
| `event` | `events[]` from Wikidata cache | ✅ exists |
| `context` | `era_context.json` via `get_context_for_year()` | ✅ exists |
| `era` | `format_era_display()` (top era name only) | ✅ exists |
| `ongoing` | `get_eras_for_year()` second-highest weight era | ✅ exists |
| `source_url` | Wikidata search URL or null | ✅ trivial to build |

Everything needed is already in the data layer.

### 4. Variety — no server-side tracking

The developer confirmed: variety is **per-user**, not global. Server-side tracking would share counters across all users (suppressing the best fact for everyone after one person sees it). Decision: **no server-side per-user tracking**. Use date-seeded rotation. Top-ranked event always shown — just a different one each day.

### 5. Web app — strip to bare minimum

**Delete everything except:** clock display (HH:MM), year number, fact text.

**Delete:**
- 👍/👎 reaction buttons (not urgent; reactions table in SQLite can stay)
- 💾 save button and saved facts panel
- Topic chips (🌍 All / ⚔️ History / etc.)
- Custom topic creator
- Era stats panel (📊)
- Any other UI chrome that isn't the clock itself

Topics and reactions are good long-term ideas but are complexity the project cannot afford right now. They can return later, properly designed.

### 6. LLM scorer — keep, fix, test

The scorer (`scorer.py`) is a core differentiator. It filters Wikidata events using `gpt-4o-mini`, removing boring entries and keeping only what a general curious audience would find interesting. Cost: ~$1–4 total to score all 1440 years; ~$4/month max on re-runs.

**Why it has never run (race condition found):**

The deploy sequence has a timing bug:
1. Container restarts → warmer starts, finds cache **already warm** → skips all 1440 years in <10 seconds (no sleep on skipped entries)
2. `deploy.sh` then calls `--clear-cache` → clears everything
3. Warmer is **already done**. Won't run again until 04:00 UTC.
4. Cache stays empty. Next page load hits live Wikidata. Scorer never called.

**Fix:** `--clear-cache` must happen *before* the container restarts. Then the warmer finds an empty cache and processes everything with scoring enabled.

**Plan:** Test the scorer on 10 specific years before trusting it broadly. Watch logs with:
```bash
docker compose -f docker-compose.prod.yml logs --since 24h api > ~/warmer-logs.txt
```

### 7. `era_exposure` — dead feature, partly clean up

`era_exposure` tracks how many times each named era has appeared. It is stored in both SQLite (server) and `localStorage` (client) with no sync between them. Multiple reviewers (Round 1 + Round 2) confirmed it influences nothing — it increments a counter displayed in a stats panel that nobody uses, and it violates HTTP semantics (GET endpoint with a write side effect).

**Decision:**
- Delete the UI panel (📊 Era stats)
- Keep the SQLite table — costs nothing, might be useful for the artsy engineer or future analytics
- Keep `increment_era_exposure()` server call — it's cheap and the data may become useful

### 8. Code cleanup — what to delete

| Item | Decision | Reason |
|---|---|---|
| `flutter_app/` | **Delete** | Entirely `.dart_tool` cache and Chrome browser data. No source code of value. |
| `_archived/clock.py` | **Delete after reading** | Original standalone terminal clock. Read once before deleting — shows the Wikidata fetch logic that became `fetcher.py`. |
| `_archived/clock_rich.py` | **Delete after reading** | Original Rich-formatted terminal clock. **Read before deleting** — the visual layout (panel widths, colors, multi-line display) is the reference for the future `pip install yearclock` CLI. |
| `feedback/` | **Keep** | Two rounds of expert review with executable code inside. Mine for tests and prescriptions. |

### 9. Physical clock — the artsy engineer plan

- **Prototype:** Raspberry Pi + whatever display is available (trashy bin finds welcome)
- **Demo mode:** Pi runs Chromium in kiosk mode pointed at `historieklokka.no` — zero new code
- **Offline fallback:** Static JSON file with 1440 facts (one per clock year). Already have this data in `era_context.json` + `future_events.json`. No internet = show static fact.
- **Production version:** Hardware decisions deferred to the artsy engineer. Possibly e-ink display + custom PCB, grant-funded, library/school installation.
- **API contract:** The artsy engineer needs a clean, documented `/api/v1/now` endpoint. That's the only dependency between the software and hardware work.

### 10. UX philosophy — quiet page, no onboarding

- No onboarding tooltips or modals. A quiet page feels safer and more trustworthy to new visitors.
- The design should make the concept self-evident. A designer will help make it clearer through visual design alone.
- "Catering to those who get it" is the right philosophy — the intended audience is curious people who recognise the clock metaphor immediately.

### 11. Levels of success

| Level | Description | Status |
|---|---|---|
| 1 | Works for me and close friends daily — fact loads instantly on every page open | **Not yet reached** |
| 2 | Linux nerds use `/now` in `.bashrc` — needs documented endpoint + README one-liner | Not yet |
| 3 | Library says yes to physical installation | Not yet |
| 4 | Library employs a historian for a month to curate facts | Dream |

**Why Level 1 is not yet reached:** Page load sometimes takes 4–8 seconds to show the fact. This is caused by the `--clear-cache` timing bug leaving the cache empty. Fix the bug → cache stays warm → instant loads.

---

## Future Ideas (Not Now)

### Crowdsourced curation
Any time a user likes or saves a fact, that factoid is permanently stored and recycled into the event pool for that year. This crowd-sources editorial curation: boring facts get ignored, good facts get liked and promoted. Requires: a persistent `community_events` table, a mechanism to weight liked facts higher in the rotation, and a minimum volume of users before the signal is meaningful. **Write this down for future self — do not build now.**

---

## Immediate Priority Order

1. **Fix `--clear-cache` timing in `deploy.sh`** — clear cache *before* container restart so the scorer finally runs
2. **Wire `index.html` to the API** — delete the ~120-line SPARQL block, replace with `fetch('/api/v1/year/{year}')`. One afternoon. Activates the SQLite cache for web users, removes IP leak, unifies state.
3. **Strip the UI** — delete topics, reactions UI, save button, era stats panel, thumbs
4. **Add `/api/v1/now` endpoint** — prerequisite for CLI, artsy engineer, README one-liner
5. **Review + selectively add tests from `feedback/round-002/`** — test code is embedded in markdown; extract carefully, check against current API shape
6. **Document the one-liner in README** — `curl https://historieklokka.no/api/v1/now | jq .`
7. **Delete `flutter_app/`, then `_archived/`** (after reading `clock_rich.py`)

---

## What the Feedback Folder Contains

Two rounds of expert review (`feedback/round-001/` and `feedback/round-002/`) filed by seven specialist roles: Senior UX Designer, Software Architect, Senior Developer, Performance Engineer, QA Engineer, Security Champion, DevOps/SRE.

Round 2 contains **executable code** — test files, exact diffs, middleware snippets — ready to extract. The developer had not read these before this grilling session.

Key prescription that 5/7 reviewers agreed on: **wire the web app to the FastAPI backend** (delete the duplicate SPARQL block in `index.html`). This is the single highest-leverage change in the codebase.
