# Known Issues & Incident Log

External data quality issues discovered in production. These are mostly upstream
(Wikipedia/Wikidata) rather than bugs in our code, but worth documenting for context
and to track our defensive responses.

---

## 2026-05 · Year 1726 showed "Fourteen-segment display" as historical event

**Observed:** Clock at 17:26 showed:
> Fourteen-segment display — Source: Wikidata

**Root cause (two separate issues):**

1. **Old Wikidata SPARQL cache (primary cause).** The event came from the *old*
   Wikidata SPARQL pipeline, which was replaced with the Wikipedia-based pipeline in
   early 2026. The production SQLite cache still contained raw SPARQL results (no LLM
   scoring applied) tagged `source: "Wikidata"`. Someone had added an incorrect
   `P585` (point-in-time) property of 1726 to the Fourteen-segment display Wikidata
   item (Q189347), causing it to appear in year-filtered SPARQL results.

2. **Wikipedia's "1726" article was also corrupted (secondary finding).** At the same
   time, the English Wikipedia article titled "1726" (pageid 35855) had been replaced
   with Seven-segment display content as part of a March 2026 merge proposal gone
   wrong. Had the Wikipedia pipeline fetched 1726 fresh, it would have received the
   same kind of bad data from Wikipedia directly.

**Our code's behavior (old pipeline):** The fetcher stored raw SPARQL labels directly
into cache with no LLM filtering. This is why the text was unscored and the source
said "Wikidata" rather than "Wikipedia".

**Defensive fix applied (2026-05-10):** The Wikipedia fetcher now returns `[]`
immediately if the fetched article has no `== Events ==` section, rather than falling
back to parsing the full article wikitext. This prevents corrupted or misidentified
year articles (like the segment-display article) from producing garbage events.
Era-context handles the gap cleanly.

**Action required:** Clear the production cache to evict all old SPARQL entries:
```bash
./deploy.sh root@77.42.120.231 --clear-cache
```

---

## 2026-05 · Several year articles corrupted on Wikipedia

**Observed** while debugging the 1726 incident (confirmed via Wikipedia API):

| Year | Wikipedia article title | Problem |
|------|------------------------|---------|
| 500  | 1000 (redirected?)     | Article has sections: Buildings, Currency, Electronics, Games, Lists — not a year article |
| 1000 | 1000                   | Article has sections: Vehicles, See also — not a year article |
| 1726 | 1726                   | Article contains Seven-segment display content (merge proposal gone wrong) |

These are Wikipedia-side issues. Our fetcher now correctly returns `[]` for all of
them (no Events section found), so they fall back to era-context.

---

## Ongoing · Year 1453 uses "Global events" section (not "Events")

**Observed:** `fetch_wikipedia_events(1453)` returns 0 candidates, despite the fall
of Constantinople being one of the most consequential events in world history.

**Root cause:** Wikipedia's 1453 article uses `== Global events ==` as the section
header instead of `== Events ==`. Our regex only matches `Events` or `Events and X`.

**Status:** The structure is more complex than a simple section rename — "Global events"
contains only prose (no bullets); the actual events are split across regional level-2
sub-sections (`== Europe ==`, `== Asia ==`, etc.). Fixing this requires a more
substantial change to the section-extraction logic. Year 1453 currently falls back to
era-context (Late Middle Ages). Tracked as a future improvement.

---

## Notes on Wikipedia reliability

Wikipedia year articles are crowd-maintained and occasionally subject to vandalism,
accidental page swaps from merge proposals, or structural variation (section names
differ across eras). Key observations:

- Articles from ~800–1900 usually have a clean `== Events ==` section
- Articles for very early years (<500) and some round numbers (1000) are frequently
  corrupted or point to disambiguation/list articles
- Articles for recent decades (1900s–2000s) are typically well-maintained but were
  temporarily rate-limited (HTTP 429) during rapid sequential fetching
- Our nightly warmer fetches at 5s/year (~12/min), well within Wikipedia's limits
- The LLM scorer prompt instructs GPT-4o-mini to return `[]` if "nothing is
  interesting enough" — but this is best-effort; the LLM can still be confused by
  anachronistic input (e.g. receiving display-technology labels for year 1726 and
  writing plausible-but-hallucinated Age of Reason text instead)

**Philosophy:** We rely on Wikipedia as our primary source and accept that upstream
errors will occasionally occur. Our defence is layered:
1. Boring-pattern filter (removes sports, eclipses, Q-codes, etc.)
2. LLM scorer (selects and rewrites interesting events; supposed to reject garbage)
3. No-Events-section guard (returns [] for clearly non-year articles)
4. Era-context fallback (always shows *something* meaningful)

We do not attempt to validate every Wikipedia article or compare events against known
timelines. That would be over-engineering; the era-context fallback is an acceptable
floor.
