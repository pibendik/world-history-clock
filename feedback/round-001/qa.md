# Year Clock — QA Review Round 001

**Reviewer:** QA Engineer (10 yrs experience)  
**Date:** 2025-07-13  
**Scope:** `web/index.html` (client logic), `data/epochs.py`, `server/fetcher.py`, `flutter_app/lib/main.dart`, `web/sw.js`

---

## 1. Current Test Coverage

**What exists:** Zero meaningful tests. The Flutter `widget_test.dart` is the default Flutter scaffolding smoke test that references `MyApp` and a counter widget — both of which don't exist in this codebase. It would fail to compile. There are no unit tests for `epochs.py`, no pytest tests for `fetcher.py`, and no JavaScript test suite (Vitest, Jest, or otherwise) for the core logic in `index.html`.

**Baseline risk:** Extremely high. All logic — year calculation, topic filtering, era exposure tracking, dislike suppression, event buffering, SPARQL querying — is entirely untested. Any regression introduced during development is invisible until a human happens to notice it at runtime. Phase 2 added reactions, saved facts, custom topics, era stats, prev/next navigation, and a Flutter client simultaneously, which is a high-risk parallel delivery with zero regression safety net.

---

## 2. Year Calculation Edge Cases

**How it works:** `getYearFromTime(hh, mm)` does `parseInt(padStart(hh,2) + padStart(mm,2))`, producing integers 0–2359. The Flutter client uses `now.hour * 100 + now.minute`, which is arithmetically equivalent.

**Issues found:**

- **`00:00 → 0`**: Correct numerically, but `parseInt("0000")` returns `0`. The year display does `String(year).padStart(4,'0')` so it renders "0000". The `eraLabel` function has a special case `if (year === 0) return 'Year Zero / 1 BC'`. This is cosmetically fine, but epoch data uses signed integers — year 0 doesn't exist historically (Julian calendar goes 1 BC → 1 AD). No epoch has `start: 0`; the epochs covering this period use negative numbers. So `getErasForYear(0)` may return matches (e.g. Classical Antiquity start: -800, end: 600 — yes, 0 is in range) but the year labelled "0000" is historically ambiguous.
- **`23:59 → 2359`**: The `fetchEventData` function hard-codes `if (year > 2025)` as the "future" threshold. Year 2359 triggers the future branch, displaying "Year 2359 hasn't happened yet." This is correct behaviour but untested.
- **`01:09 → 109`**: `parseInt("0109")` = 109. Correct. But `parseInt` with a leading zero is technically parsed as decimal in modern JS (not octal), so this is safe — but fragile: if the string-building logic ever changed to omit padding, `parseInt("109")` would still work, but `parseInt("09")` for 00:09 would also be fine since ES5. Low risk, but worth a unit test.
- **Flutter boundary mismatch:** `_navigateYear` in Flutter does `_displayYear + delta` with **no clamping**. A user at year 0 pressing Prev would navigate to year -1 and fire `GET /year/-1`. The web client does `Math.max(0, Math.min(2359, base + delta))`. This is an inconsistency. The Flutter client can produce negative or >2359 year requests to the server — the server's behaviour for these inputs is undefined and untested.

**Specific test cases:**

- `TC-YEAR-01`: Assert `getYearFromTime(0, 0) === 0`
- `TC-YEAR-02`: Assert `getYearFromTime(23, 59) === 2359`
- `TC-YEAR-03`: Assert `getYearFromTime(1, 9) === 109`
- `TC-YEAR-04`: Assert `getYearFromTime(0, 1) === 1` (not 10)
- `TC-YEAR-05`: Flutter: press Prev at year 0, assert request URL year parameter ≥ 0

---

## 3. Wikidata Failure Scenarios

**In `fetcher.py` (`_run_query`):**

- **Network timeout (8s):** `requests.RequestException` is caught, returns `[]`. Correct, but silently returns an empty list — no logging, no metrics, no retry. If both queries time out, `fetch_wikidata_events` returns `[]`, `get_events_for_year` returns `[]`, and nothing is cached (the `if events:` guard prevents storing empty results). Next call for the same year will hit Wikidata again, potentially hammering a slow endpoint.
- **Malformed JSON:** `ValueError` is caught. Returns `[]`. Safe.
- **Empty results:** Returns `[]`. The `if events: store_events(...)` guard means an empty result is never cached, causing repeated fetches for years with genuinely no Wikidata entries. This is a cache stampede risk for ancient years (e.g., year 3) where no events exist.
- **Rate limiting (HTTP 429):** `resp.ok` is False, returns `[]`. The 429 response is treated identically to a 404 or 500 — no backoff, no retry-after header inspection, no alerting. Under load, the server could silently degrade.

**In the web client (`fetchWikidata`):**

- The catch block at the top of `fetchEventData` is `catch (_) {}` — fully silent. If `fetchWikidata` throws, the era fallback text is shown. The user sees content, but there's no distinguishing between "no events found" and "network totally failed."
- The label length filter (`len >= 15` in Python, absent in the JS client) creates a discrepancy: the JS SPARQL queries do not filter by label length. Events with short labels (e.g., "Battle of X" at 12 chars) would appear in the web client but be dropped by the server. This is a divergence that could cause confusion during cross-client debugging.

**Specific test cases:**

- `TC-WIKI-01`: Mock `requests.get` to raise `Timeout`. Assert `_run_query` returns `[]` without raising.
- `TC-WIKI-02`: Mock a 429 response. Assert `_run_query` returns `[]` and does not retry within the same call.
- `TC-WIKI-03`: Mock a 200 with `{"results": {"bindings": []}}`. Assert `fetch_wikidata_events` returns `[]` and `get_events_for_year` does NOT call `store_events`.
- `TC-WIKI-04`: Mock a 200 with malformed JSON (not valid JSON string). Assert `_run_query` returns `[]`.
- `TC-WIKI-05`: Mock both queries returning only labels shorter than 15 chars. Assert `get_events_for_year` returns `[]` (server) but web client would have returned those labels — document the discrepancy.

---

## 4. Topic Filter Correctness

**How it works:** `classifyTopics(labels)` does case-insensitive substring matching against `TOPIC_KEYWORDS`. `getNextForTopic` filters `entry.events` using the same keywords.

**False positive risk:**

- The keyword `"star"` in Astronomy would match "The First Star Wars film" (Literature event) or "Muhammad Ali became a star" (History event). Substring matching with no word-boundary check is the root cause.
- The keyword `"built"` in Art & Architecture matches any sentence containing "built" — e.g., "The Ottoman army built a new fortress" would appear under both History and Art & Architecture.
- The keyword `"play"` in Literature would match "A play was performed" but also "He began to play chess competitively."
- The keyword `"moon"` in Astronomy matches "Moon Festival celebrated" (cultural event, not astronomical).
- Custom topics with a keyword like `"king"` would match "King cobra discovered" under Science.

**Specific test cases:**

- `TC-TOPIC-01`: Given labels `["The Battle of Agincourt was fought"]`, assert `classifyTopics` includes "History" (`battle` keyword) but NOT "Literature".
- `TC-TOPIC-02`: Given labels `["Johann Sebastian Bach was born"]`, assert "Music" is matched (contains `"bach"` — wait, `"bach"` is not in keyword list). Actually this is a false **negative**: "Bach was born" does NOT match any Music keyword unless it contains `music`, `symphony`, `opera`, etc. This is a real gap.
- `TC-TOPIC-03`: Given labels `["The first Star Wars film released"]`, assert "Astronomy" is NOT matched despite containing `"star"`.
- `TC-TOPIC-04`: Empty labels array — assert `classifyTopics` returns a Set containing only `"All"`.
- `TC-TOPIC-05`: Custom topic with keyword `""` (empty string after trim/filter) — verify it never matches.

---

## 5. Era Tracker Invariants

**Can `era_exposure` go negative?** No — `incrementEraExposure` only adds 1 to a value that starts at 0. The count can never go below 0. However:

- **`getEraExposureScore` divides by `era.weight`**. If an epoch ever has `weight: 0` (possible if someone adds a malformed entry to epochs.json), this produces `NaN` or `Infinity`. The sort in `pickBestEra` would behave unpredictably with `NaN` comparisons.
- **Unbounded growth:** `era_exposure` counts in `localStorage` grow indefinitely. After years of use, the counts become very large numbers. JavaScript's `JSON.stringify` handles this fine, but `localStorage` has a ~5MB limit. With ~55 eras, each stored as `"era_name": 99999`, this is unlikely to overflow but there's no eviction policy.
- **Year with no era:** `getErasForYear(year)` returns `[]` for years outside all epoch ranges. `pickBestEra` returns `null`. The `tick()` function guards with `if (eraBadgeEl && bestEra)` — so `eraBadge` stays empty. `getEraFallbackText` handles this with a generic message. **No crash**, but the coverage is thin: years like 2026–2358 have no epoch (except Space Age and Digital Age which end at 9999 — so they're covered). The only true gap would be negative years before -3500 (before Bronze Age). `getYearFromTime` never produces negative numbers, so this can't happen in practice.
- **`epochs.py` loads the JSON file on every call** — `_load_eras()` has no caching. In a request-heavy server, this means disk I/O on every era lookup. For a hobby project this is acceptable, but under load it would be measurable.

**Specific test cases:**

- `TC-ERA-01`: Call `get_eras_for_year(500)` — assert returns eras sorted by weight descending, top era has highest weight.
- `TC-ERA-02`: Call `get_eras_for_year(9999)` — assert only "Space Age" and "Digital Age" are returned (end: 9999).
- `TC-ERA-03`: Call `get_eras_for_year(-9999)` — assert returns `[]`, `format_era_display` returns `""`.
- `TC-ERA-04`: Inject epoch with `weight: 0`, call `getEraExposureScore` — assert no division-by-zero exception in JS (returns `NaN`) and sort is handled gracefully.
- `TC-ERA-05`: Call `incrementEraExposure` 1000 times for the same era — assert `localStorage` key exists and value is 1000, no corruption.

---

## 6. Prev/Next Navigation Boundaries

**Web client:** `navigate(delta)` clamps to `Math.max(0, Math.min(2359, base + delta))`. At year 0, Prev is correctly disabled (`viewingYear <= 0`). At year 2359, Next is correctly disabled. **This is handled correctly.**

**Edge cases missed:**

- When in live mode (not viewing), `prevBtn.disabled` is set to `!lastYear || lastYear <= 0`. At exactly `lastYear === 0` (midnight, 00:00), `lastYear <= 0` is true, so Prev is disabled. Correct. But `!lastYear` is `true` when `lastYear` is `0` (falsy in JS!). This means on initial load before `tick()` fires, both buttons could be disabled — which is fine. But if `lastYear === 0`, `!lastYear` evaluates to `true`, so the condition is `true || false` → `true`, meaning Prev is **always disabled at midnight** even after `viewingYear` is set. This is a subtle bug: the falsy check on `lastYear === 0` means you can't navigate Prev from midnight in live mode.
- **Flutter client `_navigateYear`:** No boundary clamping. Can navigate to year -1 or year 2400. The server receives these values and there's no input validation visible in the server code shown. This is a correctness bug.

**Specific test cases:**

- `TC-NAV-01`: Set `lastYear = 0`, call `updateNavStatus()` in live mode — assert prevBtn is disabled AND the reasoning is documented (it's disabled because 0 is the minimum, not because lastYear is falsy).
- `TC-NAV-02`: Set `viewingYear = 2359`, call `navigate(+1)` — assert `viewingYear` remains 2359, nextBtn is disabled.
- `TC-NAV-03`: Set `viewingYear = 0`, call `navigate(-1)` — assert `viewingYear` remains 0, prevBtn is disabled.
- `TC-NAV-04`: Flutter — mock server to reject year -1 — assert UI shows an error or stays on year 0.

---

## 7. Like/Dislike Persistence

**Mechanism:** Reactions stored in `localStorage` under key `clockapp-reactions` as `{year::text: {year, text, source, reaction, timestamp}}`.

**Issues:**

- **localStorage cleared:** All reactions are lost. No server-side persistence. Dislikes are gone, so previously disliked events will reappear. This is a silent data loss with no warning to the user.
- **Cross-device sync:** Zero. Reactions are entirely client-side. A user who liked facts on their phone sees nothing on their laptop.
- **Reaction key collision:** The key is `${year}::${text}`. If two different events for the same year happen to have the same text (e.g. Wikidata returns duplicate labels with minor differences), only one reaction is stored. In practice Wikidata labels are distinct, so low risk.
- **Flutter client reactions:** Posted to the server (`POST /reaction`). The server presumably persists them in a database (via `db.py`). This means reactions in Flutter ARE persistent (server-side) while web reactions are NOT (localStorage only). This is a product-level inconsistency: the same user action has different durability depending on platform.
- **Dislike suppression in `fetchEventData`:** The loop iterates `total` times looking for a non-disliked event. If ALL events for a year are disliked, the loop exhausts and falls back to `getEraFallbackText`. The user is not told "you've disliked all events for this year." Silent degradation.

**Specific test cases:**

- `TC-REACT-01`: Like an event, clear localStorage, reload — assert like button is not active.
- `TC-REACT-02`: Dislike all events for a year, call `fetchEventData(year)` — assert result is `getEraFallbackText(year)` (not an infinite loop or crash).
- `TC-REACT-03`: Flutter POST /reaction with HTTP 500 — assert `_showFeedback('Network error')` is called (currently shows "Network error" on `catch (_)` — verify the message is user-visible, not just a snack toast that disappears in 2 seconds while they're not looking).

---

## 8. Save/Favorites

**Issues:**

- **No maximum saved count:** `saveCurrentFact` does `saved.unshift(...)` with no cap. A user could accumulate thousands of saved facts, bloating `localStorage`. There's no pagination in `renderSavedPanel`. With 1000 entries, `innerHTML` assignment with `saved.map(...)` would freeze the UI momentarily.
- **Deduplication exists:** `if (saved.find(s => s.key === key)) return;` — correctly prevents duplicate saves. Good.
- **Flutter saves are server-side (`POST /saved`)** while web saves are localStorage-only. Same platform inconsistency as reactions. No cross-device visibility.
- **XSS risk in saved panel:** `renderSavedPanel` uses `innerHTML` with `s.text` inserted as `${s.text}` inside a `div`. If `s.text` contained `<script>` or `<img onerror=...>` — sourced from Wikidata — this is a stored XSS vector. Wikidata labels are generally plain text, but this is not guaranteed. The save key is also escaped only for `"` characters (`replace(/"/g, '&quot;')`), not for `<>`.

**Specific test cases:**

- `TC-SAVE-01`: Save 1000 facts programmatically, open saved panel — assert no UI freeze (measure render time < 200ms) or add virtual scrolling.
- `TC-SAVE-02`: Attempt to save the same fact twice — assert `loadSaved().length` does not increase on the second save.
- `TC-SAVE-03`: Inject a label containing `<img src=x onerror=alert(1)>` from a mocked Wikidata response, save it, open saved panel — assert no script execution (XSS test).
- `TC-SAVE-04`: Remove all saved facts — assert `savedCount` badge shows "0" and panel shows the empty-state message.

---

## 9. Custom Topics

**Issues:**

- **Empty keyword after trim:** `kwText.split(',').map(k => k.trim().toLowerCase()).filter(Boolean)` — correctly filters empty strings after trim. If all keywords are spaces/commas, `keywords.length` is 0 and the function returns early. This is handled.
- **Empty topic name with spaces:** `name = value.trim()` — correctly rejects blank names. Handled.
- **Very long topic names:** `maxlength="30"` in HTML limits to 30 chars. However, this is enforced by the browser only. No server-side validation equivalent exists. In the chip rendering, a 30-char label will overflow the chip visually on small screens.
- **Special characters in topic name:** A topic named `<script>` would be inserted via `chip.innerHTML = \`🏷️ ${ct.label} ...\`` — **XSS vector**. A user who names a custom topic `<img src=x onerror=alert(1)>` would execute arbitrary JS on chip render. This is a self-XSS (user attacking themselves) but if custom topics are ever synced server-side it becomes a stored XSS.
- **Duplicate topic name:** `idx = topics.findIndex(t => t.label === name)` — updates existing topic if name matches. This is correct deduplication behaviour.
- **Keyword `"star"` in custom topic matching `"star wars"`:** Same false positive issue as built-in topics.

**Specific test cases:**

- `TC-CUSTOM-01`: Submit custom topic with name `"  "` (spaces only) and valid keywords — assert topic is NOT saved.
- `TC-CUSTOM-02`: Submit custom topic with valid name and keywords `",,,,"` (commas only) — assert topic is NOT saved.
- `TC-CUSTOM-03`: Submit custom topic with name `<b>Bold</b>` — assert the chip label renders as literal text, not as HTML.
- `TC-CUSTOM-04`: Add a custom topic, switch to it, then delete it — assert `activeTopic` reverts to `"All"` and events reload.
- `TC-CUSTOM-05`: Add custom topic, reload page — assert it persists from localStorage.

---

## 10. PWA Offline Behaviour

**Service worker strategy:**

- Static assets (`/`, `/index.html`) are cached on install (cache-first).
- Wikidata requests bypass the service worker entirely (`return;` — falls through to network). This means the browser makes a direct network request with **no fallback**.
- `sw.js` only caches `/` and `/index.html`. The manifest, icons (`icon-192.png`), and any fonts are NOT in `STATIC_ASSETS` — they'll be served from cache only if previously fetched and matched by the `cached || fetch(event.request)` fallback. First-visit offline would miss icons.

**What the user sees offline:**

1. The HTML shell loads from cache — clock ticks, era labels appear. ✅
2. Year changes trigger `fetchWikidata` which fires two `fetch()` calls to `query.wikidata.org`.
3. The service worker returns nothing (the `return;` means no `respondWith`). The browser fires the fetch itself — it fails with a network error.
4. `fetchWikidata` throws (the `await fetch(url)` rejects), caught by `catch (_) {}` in `fetchEventData`.
5. `fetchEventData` returns `getEraFallbackText(year)` — the era description text. ✅ (degraded gracefully)
6. User sees era description, not a loading spinner. This is acceptable offline UX but undocumented.
7. If the user was previously online, `yearCache` (in-memory only) and `eventBuffer` (in-memory only) are gone on page reload. No IndexedDB or Cache API persistence for Wikidata events.

**Specific test cases:**

- `TC-PWA-01`: Load app online, go offline, navigate to a new year — assert era fallback text is shown (not a blank card or unending spinner).
- `TC-PWA-02`: Load app, go offline, reload the page — assert `index.html` loads from cache, clock ticks.
- `TC-PWA-03`: Go offline, check that manifest and icons are served — assert no broken images or manifest errors.
- `TC-PWA-04`: Update `sw.js` cache name to `yearclock-v2`, deploy — assert old `yearclock-v1` cache is deleted on activate (verified by checking `caches.keys()`).

---

## 11. Flutter Client HTTP Error Handling

**Current behaviour:**

```dart
// _fetchYear
} catch (_) {
  if (mounted) setState(() => _loading = false);
}
```

All HTTP errors (5xx, connection refused, timeout) are silently swallowed. `_yearData` is left as its previous value or `null`. When `_yearData` is null, `_filteredEvents()` returns `[]`, and the UI shows nothing (no event text rendered). The user sees a blank event area with no loading indicator and no error message.

**Specific issues:**

- **HTTP 500 from server:** `resp.statusCode` check `if (resp.statusCode == 200 && mounted)` — 500 falls through, `_loading` is never set to false because the `setState` inside the `if` block doesn't run. **This is a bug**: the loading spinner stays visible indefinitely on a 5xx response. (The catch block only handles thrown exceptions, not non-200 status codes.)
- **Server not running:** `catch (_)` fires, `_loading = false`. Blank screen, no error, no retry, no message.
- **`_postReaction` / `_postSave` failures:** `catch (_)` calls `_showFeedback('Network error')` — this is visible to the user via a 2-second feedback message. Better than `_fetchYear`, but the 2s toast is easy to miss.

**Specific test cases:**

- `TC-FLUTTER-01`: Mock server returning 500 on `/year/{year}` — assert loading indicator disappears and an error message is shown to the user.
- `TC-FLUTTER-02`: Mock connection refused — assert user sees "Offline" or "Server unavailable" message.
- `TC-FLUTTER-03`: Mock slow server (>5s) — assert loading indicator appears, does not freeze the UI, and times out gracefully.
- `TC-FLUTTER-04`: Confirm `_loading` is reset to false on non-200 status codes.

---

## 12. Regression Risk from Phase 2

Phase 2 delivered reactions, saved facts, custom topics, era stats, prev/next navigation, EventBuffer prefetching, YearCache topic cycling, Flutter client, and PWA simultaneously. The highest-risk regressions are:

1. **EventBuffer + topic switch:** Topic change calls `eventBuffer._store.clear()` then `fetchEvent(lastYear)`. If `fetchEventData` is mid-flight for that year (prefetch), a race condition could write a stale (wrong-topic) event into the buffer after the clear. The buffer would serve the wrong topic event on the next minute tick.
2. **Dislike + buffer invalidation:** After disliking, `eventBuffer._store.delete(lastYear)` then `fetchEvent(lastYear)` is called. But `yearCache` still holds the disliked event. The next call to `getNextForTopic` may cycle back to the disliked event after it has been seen `pool.length` times.
3. **Navigation year display vs. tick:** When `viewingYear` is set, `tick()` skips `fetchEvent` but still calls `updateNavStatus()` and updates `elYear`. If `lastYear` changes during navigation, the year display card shows the live year while the event card shows the navigation year — a confusing split-brain display.
4. **`allLabels` global mutation:** `allLabels` is a module-level variable mutated in `tick()` (reset to `[]`) and in `fetchEvent` (assigned from cache). Concurrent `fetchEvent` calls for different years (live + prefetch) could overwrite `allLabels`, causing `classifyTopics(allLabels)` to show wrong topic highlights.
5. **Custom topics persisted but no version migration:** If `TOPICS` or `TOPIC_KEYWORDS` change in a future release, a user's saved `clockapp-topic` could reference a now-deleted topic. `getActiveKeywords()` returns `null` for unknown topics, silently falling back to "All" filtering — but the chip is never rendered, so the user sees an active topic with no matching chip (invisible state).

---

## 13. Proposed Test Pyramid

### Unit Tests (target: 40 tests)

**Language: JavaScript (Vitest) for client logic, pytest for Python**

| ID | Target | Test Description |
|----|--------|-----------------|
| U-01 | `getYearFromTime` | All 1440 minute combinations produce expected integer (spot-check 00:00→0, 12:30→1230, 23:59→2359) |
| U-02 | `getYearFromTime` | Input `(1, 9)` → 109, not 19 or 190 |
| U-03 | `getErasForYear` | Year 1066 returns Viking Age and Early Middle Ages (among others), sorted by weight desc |
| U-04 | `getErasForYear` | Year -5000 returns `[]` |
| U-05 | `getErasForYear` | Year 1945 returns WWII era (weight 8) as top result |
| U-06 | `classifyTopics` | Labels with "battle" → History in matched set |
| U-07 | `classifyTopics` | Labels with "star" (film context) → Astronomy false positive documented / word-boundary fix |
| U-08 | `classifyTopics` | Empty labels → Set contains only "All" |
| U-09 | `YearCache.store` | Second store for same year does not overwrite first (preserve cycling position) |
| U-10 | `YearCache.getNextForTopic` | Cycles through filtered events, wraps around at end |
| U-11 | `YearCache.getNextForTopic` | Falls back to all events when no keyword match |
| U-12 | `EventBuffer.has` | Returns false while `fetching: true` |
| U-13 | `EventBuffer.prefetch` | Clamps prefetch targets to 0–2359 |
| U-14 | `navigate` (web) | At year 0, delta -1 → stays at 0 |
| U-15 | `navigate` (web) | At year 2359, delta +1 → stays at 2359 |
| U-16 | `saveCurrentFact` | Duplicate key → no second entry added |
| U-17 | `saveCurrentFact` | Empty text → returns without saving |
| U-18 | `isDisliked` | Returns true only when reaction is exactly "dislike" |
| U-19 | `getActiveKeywords` | Returns null for "All" topic |
| U-20 | `getActiveKeywords` | Returns correct array for built-in topic |
| U-21 | epochs.py `get_eras_for_year(500)` | Returns list sorted by weight descending |
| U-22 | epochs.py `get_eras_for_year(0)` | Returns at least one era (Classical Antiquity covers year 0) |
| U-23 | fetcher.py `_run_query` | Mock 200 with valid bindings → returns labels |
| U-24 | fetcher.py `_run_query` | Mock timeout → returns `[]` |
| U-25 | fetcher.py `_run_query` | Mock 429 → returns `[]` |
| U-26 | fetcher.py `_run_query` | Labels starting with "Q" are filtered out |
| U-27 | fetcher.py `_run_query` | Labels shorter than 15 chars are filtered out |
| U-28 | fetcher.py `fetch_wikidata_events` | Deduplication: same label from both queries appears once |
| U-29 | fetcher.py `get_events_for_year` | Empty result set → not stored in cache |
| U-30 | fetcher.py `get_events_for_year` | Non-empty result → stored in cache, second call returns cached |

### Integration Tests (target: 15 tests)

| ID | Target | Test Description |
|----|--------|-----------------|
| I-01 | Server API `/year/{year}` | Returns JSON with `events`, `era`, `year` keys for year 1066 |
| I-02 | Server API `/year/{year}` | Year 2026 returns `is_future: true`, empty events |
| I-03 | Server API `/year/{year}` | Year 0 returns valid response (no 400/500) |
| I-04 | Server API `/year/-1` | Returns 400 or empty response gracefully (no 500) |
| I-05 | Server API `/year/9999` | Returns valid response |
| I-06 | Server + Wikidata mock | Wikidata returning 503 → server returns 200 with era fallback |
| I-07 | Flutter + Server mock | Server 500 → Flutter loading spinner clears, error shown |
| I-08 | Flutter + Server mock | Server returns events → topic filter correctly reduces displayed list |
| I-09 | Web + Service Worker | Offline mode → era fallback text shown in event card |
| I-10 | Web localStorage | Topic persists across page reload |
| I-11 | Web localStorage | Saved facts survive reload, deduplication works |
| I-12 | Web localStorage | Custom topic persists, keywords applied correctly on reload |
| I-13 | Web + YearCache | Dislike event → same event not shown in next 10 `fetchEvent` calls for same year |
| I-14 | Web + EventBuffer | Navigate Prev/Next → events appear without loading spinner (buffer hit) |
| I-15 | Web | Midnight tick (00:00 → 00:01) → year changes from 0 to 1, new event fetched |

### E2E Tests (target: 8 tests, Playwright)

| ID | Scenario | Steps |
|----|----------|-------|
| E-01 | Smoke: clock ticks | Load page → wait 2s → assert time display updates, year visible |
| E-02 | Topic filter | Click "Science" chip → assert event card updates (text changes or spinner appears) |
| E-03 | Like flow | Wait for event → click 👍 → assert like button turns green |
| E-04 | Save and view | Click ★ Save → click 📋 Saved → assert saved panel shows the fact |
| E-05 | Dislike and skip | Click 👎 → assert new event loaded (different text) |
| E-06 | Prev/Next nav | Click Prev → assert year decreases by 1, nav status shows "Viewing X" |
| E-07 | Custom topic | Click "+ Custom" → fill name "Chess", keywords "chess,tournament" → assert chip appears |
| E-08 | Offline fallback | DevTools offline → wait for minute tick → assert card shows era text, no spinner freeze |

---

## 14. Top 5 Quality Risks (Severity × Likelihood)

| Rank | Risk | Severity | Likelihood | Mitigation |
|------|------|----------|------------|------------|
| **1** | **Silent HTTP 500 in Flutter leaves loading spinner stuck forever** | Critical (broken UI state) | High (any server error) | Fix: reset `_loading = false` for all non-200 responses; add error state widget |
| **2** | **Stored XSS via custom topic name rendered as innerHTML** | High (code execution) | Medium (user-generated; self-XSS now, stored XSS if synced) | Fix: use `textContent` or `createElement` instead of `innerHTML` for chip label |
| **3** | **Race condition: topic switch clears EventBuffer but in-flight prefetch writes stale topic event back** | High (wrong content shown) | Medium (fast topic switching) | Fix: add a `generation` counter; discard fetched results from previous generation |
| **4** | **Empty results for a year never cached → repeated Wikidata hammering for ancient years** | Medium (rate limit / 429) | High (years 1–200 have sparse Wikidata data) | Fix: cache empty results with a TTL (e.g., 24h); add negative cache |
| **5** | **`allLabels` global variable overwritten by concurrent fetches → wrong topic chips shown** | Medium (misleading UI) | Medium (navigation + prefetch overlap) | Fix: scope `allLabels` to the fetch closure, return it as part of `fetchEventData` result |

---

*End of QA Review Round 001. Total word count: ~2900 words.*
