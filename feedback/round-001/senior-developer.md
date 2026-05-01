# Year Clock — Senior Developer Review
**Round 001 · Reviewer: Senior Developer (15 years in)**

---

Alright. I've read it. Here's my honest assessment. Grab a coffee — this is going to take a minute.

---

## 1. Where's the Test Suite?

There isn't one. Not a single file. I ran `find . -name "test_*"` and got nothing from the project itself — just pip's internal vendor tests for colorama. That tells me everything I need to know about the development discipline here.

This isn't a "nice to have". `derive_year` / `getYearFromTime` is the core function of the entire application. It takes time components and maps them to a year. That's three lines of code and it has **zero test coverage**. What happens at midnight (00:00 → year 0)? What happens at 23:59 → year 2359, which is in the future? Is the future-detection threshold still `> 2025` next year? You don't know, because nothing checks it.

The Wikidata SPARQL queries filter labels that start with `"Q"` — that's a Wikidata entity ID, not a human-readable label, and it's a business rule buried in a list comprehension. Test it, or someone will break it without knowing why the labels went garbage.

The `word_wrap` function in `clock.py` — has it ever been tested with an empty string? A string with no spaces? A word longer than the width? Probably not. Probably fine. But you don't *know* it's fine, because there are no tests.

My message to the developer: **You cannot refactor code you don't have tests for.** Right now, changing anything means hoping for the best. That's not engineering, that's gambling. Write at least `pytest` tests for `derive_year`, `fetch_fact` (mocked), and `word_wrap` before you touch anything else.

---

## 2. Single-File Web App — 1,169 Lines of Inline JS

`index.html` is 1,169 lines. ~400 lines of CSS, ~700 lines of JavaScript, all in one file. No build step, no modules, no separation.

The CSS is actually decent — CSS variables, sensible naming, responsive breakpoints. But the JavaScript is a mess of responsibilities: cache management (`YearCache`, `EventBuffer`), DOM manipulation, API calls, localStorage serialization, event binding, animation triggers, topic filtering, era stats, navigation — all tangled together at the global scope.

Here's the specific problem: `fetchEventData` (pure async, returns data) and `fetchEvent` (touches the DOM) are split, which shows some awareness of separation — but then `fetchEventData` reaches directly into `yearCache._cache.get(year)?.events` on lines 779 and 799. That's breaking encapsulation on a class you defined 200 lines earlier. If you reorganize `YearCache`, you'll find these silent breaks the hard way.

There's also `allLabels` — a global variable that's written inside `fetchEventData` but never declared in the visible code structure. It's just... floating there. In 2024. In a new project.

Maintainable? No. Can one person keep it in their head? Barely. Can a second developer onboard in a day? Absolutely not.

The fix isn't complicated: split into `clock.css`, `api.js`, `cache.js`, `ui.js`. Use native ES modules. You don't need a bundler for a project this size — just `<script type="module">`. It would take a day and make everything else on this list easier to fix.

---

## 3. Error Handling

The Python side is actually not bad. `clock.py` wraps the Wikidata calls in try/except, returns `[]` on failure, and the `main()` loop handles a missing fact gracefully. The server's `fetcher.py` follows the same pattern. Points for that.

The JavaScript side, however, has this gem on line 790:

```javascript
} catch (_) {}
```

That's it. That's the entire error handler for the SPARQL fetch in `fetchEventData`. Wikidata is down? Silent. Rate-limited (429)? Silent. Network timeout? Silent. The user sees "offline" and you see nothing in the logs. No `console.error`, no telemetry, no fallback message with an HTTP status code.

On top of that, the `remove_saved` API endpoint in `server/main.py` just calls `remove_saved(key)` and returns `{"status": "ok"}` regardless of whether that key existed. Deleting a nonexistent record is a 200 OK. That's technically not wrong, but it's sloppy — a client that expects confirmation of a real deletion will be misled.

The `getReaction` and `loadSaved` functions call `localStorage.getItem` inside every call rather than caching — that means if `localStorage.getItem('clockapp-reactions')` throws a `SecurityError` (private browsing mode on some browsers), the entire `updateReactionButtons` chain goes down. The try/catch around it catches `JSON.parse` failures but not all possible localStorage errors.

---

## 4. Magic Values & Constants

`_CURRENT_YEAR = 2025` in `server/main.py`. Hard-coded. In January 2026, the server starts returning `is_future: True` for 2025. Nobody will notice until someone wonders why facts stopped showing up. Use `datetime.date.today().year`.

The SPARQL queries — `Q13406463` and `Q14204246` — appear in both `clock.py` and `server/fetcher.py`. What are those? List items? Disambiguation pages? There's no comment. If Wikidata restructures those entity types, you'll be debugging mystery filter removals. Name them.

Port numbers: presumably the server runs on some port, hardcoded somewhere. The web app's JS doesn't show an explicit API base URL (it's talking to Wikidata directly, which is fine), but if someone wires the web app to the FastAPI backend, expect another hardcoded port to appear.

The `isAntiquity` threshold in the JS is `year < 100`. In `clock.py`, there's no equivalent — it uses `year == 0` and `year > 2025` with no antiquity concept. Two different rules for the same domain concept in the same project. Pick one.

---

## 5. Code Duplication — DRY Violations

This is the biggest structural problem. The SPARQL queries `SPARQL_P585` and `SPARQL_P571` exist in **three separate files**:

- `clock.py` (lines 25–43)
- `server/fetcher.py` (lines 9–26)
- `index.html` (lines 731–744)

Three copies. Three places to update if Wikidata changes a property or you want to adjust the LIMIT. You will forget one.

The label deduplication loop (walk a list, track seen items in a set, build combined list) is copy-pasted from `clock.py` into `server/fetcher.py`. Same logic, different module, no shared function.

`derive_year` / `getYearFromTime` — same arithmetic in Python and JS. Expected, since they run in different runtimes. But the *rules* around it (future threshold, year zero handling) differ between the two implementations, which is **not** expected. That's a logic fork, not a language fork.

The `_year_cache` in `clock.py` is a module-level dict. `YearCache` in the web app is a class. `get_db()` / `get_cached_events()` in the server is SQLite. Three different caching mechanisms for the same data. The terminal app, web app, and server don't share any cache or state with each other. Every client refetches from scratch.

---

## 6. YAGNI & Over-Engineering

The era exposure tracking system — a database table, an API endpoint (`GET /eras`), in-memory stats rendering, score calculation with weights, a full stats panel UI — all to show a leaderboard of which historical eras the user has seen on their clock. Has anyone actually used this? Does it change behavior? No. It increments a counter that's displayed in a panel that requires clicking a footer link to see.

Custom topics with keyword matching is a feature that required a modal dialog, localStorage serialization, chip rendering logic, a "remove" button on each chip, and integration into `getNextForTopic` filtering. The built-in topic list covers History, Science, Music, Astronomy, Art, Literature, Math. Who is adding custom topics? What problem does this solve on day one?

The event buffer prefetching (loading ±2 years ahead) for a clock that only changes once per minute — that's premature optimization. Wikidata SPARQL already has caching server-side. You're fetching 4 extra years on every minute tick. At 3AM that's useful. At 1PM on a fast connection, it's just background noise.

The Flutter app exists. A mobile app. For a clock. That maps time to a historical year. Complete with era display and fact cards. Built while the web app still has `catch (_) {}` and zero tests. That's a choices problem, not a features problem.

---

## 7. localStorage as Database

The web app stores reactions, saved facts, custom topics, era exposure, and the active topic in `localStorage`. The FastAPI backend has a SQLite database with those exact same tables — `reactions`, `saved_facts`, `era_exposure`. They are completely separate stores that never sync.

Concretely: if you save a fact on the web app, it goes to `localStorage`. If you call `GET /saved` on the API, you get nothing. The backend's beautiful SQLite layer is functionally unused by its own web client. Why build it?

On the 5MB limit: nobody hitting this daily will fill 5MB fast — the text is compact. But `localStorage` is **per-origin** and **synchronous**. `loadReactions()` and `loadSaved()` and `loadEraExposure()` each do a full JSON parse on every call. `updateReactionButtons` calls `loadReactions()` which parses the full reactions store on every button render. As the reactions object grows over months of use, that parse time grows with it. It's not a crisis — it's death by a thousand synchronous parses.

More importantly: localStorage is cleared when the user clears browser data. One "Clear Site Data" and the user's saved facts, reactions, and era history are gone. No warning. No export. This will happen to at least one user who will be mildly annoyed. If you're going to build a "Save" feature, treat user data like it matters.

---

## 8. Async/Error Boundaries

In JavaScript: the `fetchEvent` function is `async` but is called from `tick()` without `await` and without a `.catch()`. If `fetchEventData` throws something that escapes the inner `catch (_) {}`, it becomes an unhandled promise rejection. In modern browsers that's a warning. In some server-side contexts it crashes. Always attach `.catch()` to fire-and-forget async calls.

The double `requestAnimationFrame` pattern for fading in text:
```javascript
requestAnimationFrame(() => {
  requestAnimationFrame(() => elEvent.classList.add('visible'));
});
```
This is a known workaround for CSS transition timing in the DOM, but it's fragile. If the browser batches frames, the transition still doesn't fire. Use `setTimeout(..., 0)` + force reflow, or better: use the `transitionend` event with a proper state machine.

In Python: `get_db()` opens a new SQLite connection on **every single call**. `get_reactions()`, `set_reaction()`, `save_fact()`, `remove_saved()`, `get_era_exposure()`, `increment_era_exposure()` — each opens and closes its own connection. Six database connections for a single API request to `/year/{year}`. It won't cause correctness issues with WAL mode, but it's wasteful. Use a connection pool or at minimum a thread-local connection. FastAPI with SQLite deserves at least `contextlib.contextmanager` around the connection lifecycle.

The `sys.path.insert(0, ...)` hack at the top of `server/main.py` is a red flag. Fix your package structure instead of mutating `sys.path` at import time. That's a development environment hack that will bite in production.

---

## 9. Tech Debt Inventory (Ranked by Urgency)

**1. No tests (Critical)**
Every other item on this list is harder to fix without a test suite. Write tests for `derive_year`, `fetch_wikidata` (mocked), `word_wrap`, and the year-to-era mapping *before* any other refactor.

**2. SPARQL query duplication (High)**
Three copies of the same queries. Extract into a shared module or, better, let the web app call the FastAPI backend instead of Wikidata directly. That's what the backend is presumably *for*.

**3. Web app ignores its own backend (High)**
The FastAPI + SQLite layer is built and deployed (presumably), but the web client uses `localStorage` for all user data and calls Wikidata directly for event data. Either wire the web app to the API, or delete the backend. Having both is the worst outcome.

**4. `catch (_) {}` error swallowing (Medium)**
Replace with at minimum `catch (err) { console.error('fetchEventData failed:', err); }`. Add visible error state to the UI. Users deserve to know why their facts aren't loading.

**5. `_CURRENT_YEAR = 2025` hardcoded (Medium)**
Will silently break in 8 months. One line fix: `_CURRENT_YEAR = datetime.date.today().year`. Do it now before you forget.

---

## 10. What's Actually Good

I'm not going to fake enthusiasm, but I'll be fair.

The **CSS theming** is genuinely well-done. CSS custom properties, a proper dark theme with a `future` variant that cascades through all components, sensible use of `clamp()` for responsive typography. This is clean CSS.

The **Python error handling in `clock.py`** is solid. Wikidata down? Returns `[]`. Numbers API unreachable? Returns `None`. The main loop keeps the last-known fact rather than blanking out. That's thoughtful degradation.

**WAL mode on SQLite** (`PRAGMA journal_mode=WAL`) shows that someone read the SQLite docs. That's a real-world correctness choice for concurrent access.

The **`YearCache` and `EventBuffer` split** in the web app shows an attempt at separation of concerns. The intent is right, even if the execution leaks with the direct `._cache` access.

The **service worker registration** with a silent `.catch(() => {})` is appropriate — offline capability is a nice touch and the failure case is handled without crashing.

---

## 11. The One Thing They Should Fix First

**Wire the web app to the FastAPI backend, or delete the backend.**

Right now you have two completely independent data stores for the same application: `localStorage` in the browser and SQLite via FastAPI. Reactions saved in one don't appear in the other. Events are fetched from Wikidata directly by the web app, bypassing the server's caching layer entirely. The backend is doing nothing useful for the web client.

This is the root cause of half the other issues. Once the web app calls `GET /year/{year}` for events and posts to `/reaction` and `/saved`, you can delete the Wikidata SPARQL queries from `index.html`, the `YearCache`/`EventBuffer` complexity collapses (server handles caching), `localStorage` becomes just UI preferences (active topic, nothing else), and the 5MB concern disappears.

Until then, you have a Flask API sitting in the corner looking sad while the web app does everything itself anyway. Pick a lane.

---

*This review reflects the state of the code as read. It's a side project and that's fine — but if it's going to grow, it needs a foundation that can be walked on without falling through.*
