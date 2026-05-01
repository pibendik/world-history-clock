# Year Clock — UX Design Review · Round 2

**Reviewer:** Senior UX Designer (12 yrs, mobile/web product)  
**Artifact reviewed:** `clockapp/web/index.html` — single-file PWA  
**Round:** 2 — Prescriptive Design Specification  
**Scope:** Onboarding, touch targets, IA, mode differentiation, accessibility, animation, error states, progressive disclosure, dark mode contrast, feature scope

> **Context:** Round 1 identified the major surface-level issues: absent onboarding, sub-minimum tap targets, buried topic chips, contrast failures at `opacity: 0.5`, and an incomplete live-vs-browse mode signal. This round goes deeper — each section below is a specification, not just a problem statement. Where Round 1 said *"fix this"*, Round 2 says *"build this, specifically."*

---

## 1. Onboarding Flow Design

**The goal:** A first-time user who has never heard of the app must understand the `HH:MM → YYYY` mapping within five seconds, without reading a manual.

### Proposed flow

**Trigger:** On the very first page load (detected via `localStorage.getItem('clockapp-seen') === null`), inject a semi-transparent overlay on top of the existing UI — not a modal, not a full-screen splash, but a contextual layered tooltip sequence anchored to real DOM elements.

**Step 1 — The Bridge Tooltip (auto-appear, 0 ms delay)**  
Position: absolutely placed between the `.clock-block` and the `.year-card`, centred.  
Layout: A small pill-shaped callout (~280px wide, ~60px tall) with a dark-glass background (`rgba(13,17,23,0.92)`, blur backdrop), a downward-pointing caret arrow aimed at the year number, and the text: *"Your clock reads 15:42 → year 1542."* (with `15:42` rendered in monospace teal to visually echo the HH:MM display above). Include a small `→` arrow animated with a 0.4s `translateX(+4px)` loop so the eye naturally traces the mapping direction.  
Dismiss: Auto-advances to Step 2 after 3 seconds, or on any tap.

**Step 2 — The Fact Tooltip (after Step 1 dismissal)**  
Position: Anchored to the `.event-card` left border stripe, right side.  
Layout: A right-pointing callout. Text: *"Every minute, the year changes — and so does this fact."* A subtle CSS counter shows `00:XX` counting down to the next minute. No tap required — this tooltip fades out at the minute boundary (or after 8 seconds), whichever comes first.

**Step 3 — The Chip Nudge (deferred, fires at second minute change)**  
Position: Absolutely above the first topic chip in `.topic-row`, with an upward caret.  
Layout: *"Filter facts by topic — tap a chip to focus on Science, Music, or any era."* Tap anywhere to dismiss. This is deferred to the second minute because on first load the user hasn't had time to engage with the event card yet.

**Persistence:** After all three steps complete or are dismissed, write `clockapp-seen: true` to `localStorage`. The sequence never replays. Add a `?tour=1` query-string override that replays it for testing.

**Implementation detail:** The overlay uses `pointer-events: none` except on dismiss buttons, so the clock continues to tick visibly behind the tooltip glass — reinforcing that the app is live.

---

## 2. Tap Target Remediation

Round 1 measured `action-btn` at ~28–30pt and `chip-remove` at ~10pt. Here is the exact CSS fix for each class.

### `action-btn` (Save, Like, Dislike, Saved list)

```css
.action-btn {
  min-height: 44px;
  min-width: 44px;
  padding: 0.55rem 1rem;   /* replaces 0.3rem 0.7rem */
  font-size: 0.8rem;        /* up from 0.75rem */
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 0.3rem;
}
```

The `Saved (n)` button already has a text label and icon so the wider padding won't look inflated. The Like/Dislike emoji-only buttons become square 44×44pt touch areas with the emoji centred — visually minimal but meetng HIG and WCAG 2.5.5.

### `nav-btn` (‹ Prev, Next ›)

```css
.nav-btn {
  min-height: 44px;
  min-width: 56px;
  padding: 0.55rem 1.2rem;  /* replaces 0.3rem 0.8rem */
  font-size: 0.85rem;
}
```

The nav row already uses `justify-content: space-between`, so the wider buttons naturally expand toward the edges — this actually improves the ergonomic spread, placing Prev and Next closer to the left and right thumb zones.

### `chip-remove` (✕ on custom chips)

The current `<span class="chip-remove">✕</span>` is a span with no interactivity of its own — the click is delegated to the parent `<button>`. This must change. Convert to a nested `<button>`:

```html
<button class="chip-remove" aria-label="Remove topic Chess" data-name="Chess">✕</button>
```

```css
.chip-remove {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 24px;
  min-height: 24px;
  margin-left: 0.25rem;
  padding: 2px;
  border-radius: 50%;
  font-size: 0.8rem;
  background: none;
  border: none;
  color: inherit;
  cursor: pointer;
  opacity: 0.75;
}
.chip-remove:hover { opacity: 1; background: rgba(255,255,255,0.1); }
```

24×24pt is below the 44pt ideal but acceptable within a chip context because the adjacent chip body provides additional tap surface for selection. The ✕ action is destructive, so adding a single confirmation step is still recommended: on first tap, flash a brief colour change (red border on the chip) for 600ms, requiring a second tap to confirm deletion. This prevents accidental removal with no confirmation.

---

## 3. Information Architecture — Revised Screen Layout

The current DOM order: title → clock → year card → nav row → event card → topic chips → footer.

### Proposed mobile layout (≤ 480px wide)

```
┌─────────────────────────────────┐
│  WHAT YEAR DOES IT LOOK LIKE?   │  ← 0.75rem, remove opacity
│                                 │
│      15:42:07                   │  ← primary clock, no change
│         12:42:07 PM             │  ← move inside clock-block, smaller
│                                 │
│  ┌─────────────────────────────┐│
│  │  ● LIVE    Year  1542       ││  ← year-card, live indicator left
│  │  Late Medieval              ││
│  └─────────────────────────────┘│
│                                 │
│  🌍 All  ⚔️ History  🔬 Science  │  ← CHIPS MOVED UP, above event card
│  🎵 Music  🔭 Astronomy  ···    │
│                                 │
│  ‹ Prev     Viewing 1542     Next ›│  ← nav row below chips
│                                 │
│  ┌─────────────────────────────┐│
│  │ HISTORICAL EVENT            ││
│  │                             ││
│  │ Ibn Battuta begins his      ││
│  │ journey from Tangier…       ││
│  │                             ││
│  │ Source: Wikidata            ││
│  │ [★ Save] [👍] [👎] [📋 3]   ││
│  └─────────────────────────────┘│
│                                 │
│  Era stats · Clock updates …   │  ← footer, no opacity
└─────────────────────────────────┘
```

**Key changes from current layout:**

1. **Topic chips move above the nav row and event card.** They are the primary personalisation surface; they belong in the first-scroll viewport, not below the fold. At 375pt wide, this layout keeps everything above the fold for standard phone heights.

2. **Year card integrates the live indicator** (see §4 below) — the live status now lives *inside* the year card header row, not in the nav status text.

3. **Nav row moves below the chips** but above the event card. This creates a logical flow: "What era? → Choose a topic → Navigate → Read the fact."

4. **The `📋 Saved (n)` button leaves the action row** and moves to the footer as a persistent icon button (`★ Saved (3)`) — freeing the action row to contain only per-card reactions: `[★ Save] [👍] [👎]`. Three buttons, equal width, clearly per-card.

---

## 4. Live vs. Browse Mode — Visual Differentiation

### Live mode

The year card header area shows a pulsing red dot (⏺, `#f85149`, 8×8px, `animation: livePulse 1.5s ease-in-out infinite`) followed by the word `LIVE` in `0.65rem` uppercase. The year number renders in `--year-color: #39d0c8`. The nav status reads simply `Live`.

```css
@keyframes livePulse {
  0%, 100% { opacity: 1; transform: scale(1); }
  50%       { opacity: 0.4; transform: scale(0.8); }
}
```

This is the "recording LED" metaphor — universally understood as "this is happening now."

### Browse mode

When the user presses Prev or Next, three changes fire simultaneously:

1. The live-dot disappears (fade out, 0.3s). The `LIVE` label is replaced with `BROWSING` in `--text-muted`, no dot.
2. The year card gains a 2px dashed border (replacing the solid border) using `--border` colour — signalling "you are not in the live state."
3. A `Return to Live` button appears **inside** the year card, bottom-right corner, as a small pill: `● Back to Live` (`0.7rem`, accent colour, minimum 44px touch height). This replaces the tiny inline `← Live` link in the nav status text — that pattern required the user to read a 0.7rem string; this makes it a dedicated affordance.

The nav status text changes from `Viewing 1799 • ← Live` to simply showing the year range: `← 1798  1799  1800 →` as a breadcrumb-style indicator. No dynamic innerHTML injection needed — three span elements with JS-updated text content.

---

## 5. Accessibility Deep Dive

### Missing ARIA labels — complete list

| Element | Current | Required `aria-label` |
|---|---|---|
| `#prevBtn` | ‹ Prev | `"Go to previous year"` |
| `#nextBtn` | Next › | `"Go to next year"` |
| `#saveBtn` | ★ Save | `"Save this fact"` |
| `#likeBtn` | 👍 | `"Like this fact"` |
| `#dislikeBtn` | 👎 | `"Dislike — skip this fact"` |
| `#savedListBtn` | 📋 Saved (n) | `"View saved facts, currently 3 saved"` (update count dynamically via `aria-label`) |
| `#closeSavedPanel` | ✕ | `"Close saved facts panel"` |
| `#closeEraStats` | ✕ | `"Close era exposure panel"` |
| `#eraStatsLink` | 📊 Era stats | `"View era exposure statistics"` |
| `#addCustomChip` | + Custom | `"Add a custom topic filter"` |
| Each `.chip-remove` | ✕ | `"Remove topic [label]"` (dynamic, see §2) |
| Each `.topic-chip` | (text) | Add `aria-pressed="true/false"` for toggle semantics |
| `.event-card` | — | `role="region" aria-label="Historical event for year 1542"` (update per year) |
| `#yearNumber` | — | `aria-live="polite" aria-label="Mapped year: 1542"` |
| `#timeMilitary` | — | `aria-hidden="true"` (decorative; screen readers don't need the raw HH:MM) |
| `#customTopicModal` | hidden | `role="dialog" aria-modal="true" aria-labelledby="customTopicModalTitle"` |

### Keyboard navigation flow

Define a logical tab order using `tabindex` where needed:

1. `#prevBtn` → `#nextBtn` (nav row)
2. Topic chips (left to right via natural DOM order; chip `✕` buttons receive focus via `Tab` inside the chip row)
3. `#saveBtn` → `#likeBtn` → `#dislikeBtn` → `#savedListBtn` (action row)
4. `#eraStatsLink` (footer)

Add an **explicit focus ring** for all interactive elements:

```css
:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 2px;
  border-radius: 4px;
}
```

Add `Escape` key handler to close any open panel or modal:

```js
document.addEventListener('keydown', e => {
  if (e.key === 'Escape') {
    document.getElementById('savedPanel').hidden = true;
    document.getElementById('eraStatsPanel').hidden = true;
    document.getElementById('customTopicModal').hidden = true;
  }
});
```

Add focus trap for `#customTopicModal`: on open, `document.getElementById('customTopicName').focus()`. On Tab past the last focusable element in the modal, wrap back to the first. On close, return focus to `#addCustomChip`.

### Contrast ratios for era stats panel and footer

The era stats panel uses `.saved-item-text` with inline `style="font-size:0.8rem;color:var(--text-muted)"` on `var(--bg)` background. `#8b949e` on `#0d1117` = **6.15:1** — passes AA at all sizes. No fix needed for the stats panel body text.

The footer at `opacity: 0.5` renders `#8b949e` effectively as `#4c5358` on `#0d1117` — **~2.4:1** — fails AA (minimum 4.5:1 for normal text). Fix: remove `opacity: 0.5`. The `--text-muted` colour at full opacity already provides sufficient de-emphasis relative to `--text-primary`.

---

## 6. Animation Budget

### Animations that earn their place (keep)

| Animation | Justification |
|---|---|
| `yearPulse` (scale + opacity on minute change) | Directly tied to a real event — minute boundary. Serves as a clock hand metaphor. 0.6s, not distracting. **Keep.** |
| Event text fade (opacity 0 → 1) | Prevents jarring text swap. 0.5s. **Keep.** |
| Body background transition (teal ↔ purple, 0.6s) | Communicates a meaningful state change (past ↔ future). **Keep at 0.3s — halve it.** |
| Loading dot bounce | Communicates "fetching in progress." **Keep.** |

### Animations that add noise (reconsider or remove)

| Animation | Problem | Proposed change |
|---|---|---|
| `dotBounce` on 3 dots with staggered delay | Three moving elements draws disproportionate attention. | Reduce to 1 dot bouncing, or use a simple spinner. |
| Full topic chip row re-creation (`innerHTML = ''`) | Produces a flash/pop on every render — not technically an animation, but a visual regression. | Convert to state-class toggling (`chip.classList.toggle('active', ...)`) to enable smooth CSS transitions. |

### `prefers-reduced-motion` implementation

Wrap all keyframe and transition declarations in a motion media query override:

```css
@media (prefers-reduced-motion: reduce) {
  .year-number.pulse { animation: none; opacity: 1; transform: none; }
  .event-text { transition: none; opacity: 1 !important; }
  body { transition: none; }
  .loading-dots span { animation: none; opacity: 1; transform: scale(1); }
  @keyframes livePulse { 0%, 100% { opacity: 1; } }
}
```

For `yearPulse` under reduced motion, replace the scale/opacity animation with a simple colour flash: `@keyframes yearFlash { 0% { color: #fff; } 100% { color: var(--year-color); } }` at 0.3s. This retains the information signal (year changed) without vestibular-triggering motion.

---

## 7. Empty and Error States

### Wikidata returns no results for a year

**Current behaviour:** Falls back to `getEraFallbackText(year)` — shows era descriptions in parenthetical debug-style text.

**Proposed UI:** Replace with a structured empty state card:

```
┌──────────────────────────────────┐
│ No records found for 0342        │
│                                  │
│ This year falls within the       │
│ Late Roman Empire period         │
│ (117 – 476 CE).                  │
│                                  │
│ [← Try 0343]   [→ Try 0341]      │
└──────────────────────────────────┘
```

The "Try adjacent year" buttons are context-sensitive micro-CTAs that guide the user onward rather than leaving them at a dead end.

### Network is offline

**Current behaviour:** `catch (_) {}` swallows the error silently. No UI change.

**Proposed UI:** Detect `!navigator.onLine` before the fetch. Show a distinct `offline` state:

```
┌──────────────────────────────────┐
│ 📡  You're offline               │
│                                  │
│ The last known fact for 1542     │
│ is shown. Connect to load more.  │
└──────────────────────────────────┘
```

Persist the last successfully loaded fact in `localStorage` keyed by year (separate from the main event buffer) so the offline card shows real content, not a blank. Add a `window.addEventListener('online', ...)` listener to automatically retry when connectivity returns — show a brief `↺ Reconnected — refreshing…` toast for 2 seconds.

### Year is in the future (> current year)

**Current behaviour:** Shows `"Year 2100 hasn't happened yet."` in the same event card. The body switches to purple via the `.future` CSS class.

**Proposed improvement:** The future state is already styled well (purple body, purple year). Enhance the empty card text:

```
┌──────────────────────────────────┐
│ THE FUTURE                       │
│                                  │
│ Year 2100 is 75 years away.      │
│ The Holocene Epoch continues.    │
│                                  │
│ [← Return to the present]        │
└──────────────────────────────────┘
```

Calculate "years away" from `currentYear - mappedYear` (use `new Date().getFullYear()` — fixes the hardcoded `2025` bug). The "Return to the present" button fires `returnToLive()` directly.

### Era has no events (matched topic returns zero results)

**Current behaviour:** Falls back to `(no [Topic] events found for this year — showing any)` appended to the event text.

**Proposed:** Split this into a distinct visual treatment. Show the event as normal, but below the text add a small amber-coloured informational badge:

```
⚠ No Science events found for 1542 — showing any topic
```

styled as `font-size: 0.7rem; color: #d29922; background: #2d2209; border-radius: 4px; padding: 2px 6px;`. This is less alarming than the current parenthetical, and the colour amber correctly signals "informational, not an error."

---

## 8. Progressive Disclosure

The app has three layers of complexity that must not all hit the user at once.

### Layer 1 — Core experience (immediate, no interaction required)

Clock → Year → Fact. Topic chips visible but passive. This is what every first-time visitor sees. No era stats, no custom topics, no saved panel counter until the user has seen at least one full fact.

**Implementation:** Hide the `#savedListBtn` on first visit until the user has seen ≥ 3 events (track count in `localStorage`). Show a subtle `+` badge animation when the save feature unlocks: the `★ Save` button does a single attention pulse. This defers the "📋 Saved (0)" counter (which is confusing when empty) until it has meaning.

### Layer 2 — Personalisation (unlocked after first session)

Topic filter chips are visible from the start, but the `+ Custom` chip is hidden until the user has activated at least one pre-built topic. The theory: a user who has clicked "Science" understands the chip concept; only then does the custom entry point appear. Move `+ Custom` to be a persistent icon button pinned to the right edge of the chip row (position: sticky, not at the end of the scroll). This way it is always reachable.

Era stats: Move the entry point from the footer to an info icon (ⓘ) in the corner of the year card. The year card already has `position: relative; overflow: hidden` — add a 28×28pt button at `top: 0.5rem; right: 0.5rem` with `aria-label="View era exposure"`. This is discoverable via exploration without being intrusive.

### Layer 3 — Power features (intentional discovery)

Like/Dislike reaction persistence, era exposure weight tuning, topic keyword editing. These do not need any additional entry point — they are already surfaced in the era stats panel and the custom topic modal. At this layer, the user has clearly committed to the app.

---

## 9. Dark Mode Contrast Audit

Three specific colour pairs that fail WCAG AA 4.5:1, with proposed replacements:

### Failure 1 — Footer text

**Pair:** `#4c5358` (effective; `--text-muted: #8b949e` at `opacity: 0.5`) on `#0d1117`  
**Measured contrast:** ~2.4:1  
**Required:** 4.5:1 (normal text, any size)  
**Fix:** Remove `opacity: 0.5` from `.footer`. Replace with `color: #8b949e` at full opacity.  
`#8b949e` on `#0d1117` = **6.15:1** ✓  
The `--accent: #39d0c8` era stats link already provides visual hierarchy without needing opacity reduction on the surrounding text.

### Failure 2 — `no-match` topic chip text

**Pair:** `#434a52` (effective; `--text-muted: #8b949e` at `opacity: 0.4`) on `--bg-card: #161b22`  
**Measured contrast:** ~2.3:1  
**Required:** 4.5:1  
**Fix:** Remove `opacity: 0.4` from `.topic-chip.no-match`. Communicate "not available" for this year through structure only: retain `border-style: dashed` and reduce `border-color` to `#23292f`. Set `color: #8b949e` at full opacity (5.63:1 ✓ on `#161b22`). If a WCAG 1.4.3 inactive-component exemption is preferred, mark `no-match` chips with `aria-disabled="true"` and `tabindex="-1"` to be consistent — but the chip is still tappable (it switches topic), so the exemption does not cleanly apply.  
Replacement colour for chip text: `#8b949e` at full opacity on `#161b22` = **5.63:1** ✓

### Failure 3 — Custom chip `✕` remove button

**Pair:** `#5c6470` (effective; `--text-muted` at `opacity: 0.6`) on `--bg-card: #161b22`  
**Measured contrast:** ~2.9:1  
**Required:** 4.5:1  
**Fix:** Remove `opacity: 0.6` from `.chip-remove`. Use `color: #8b949e` at full opacity (5.63:1 ✓). Increase font-size from `0.65rem` to `0.8rem`. The visual de-emphasis this opacity was providing is not meaningful — the ✕ is only present on custom chips and its function is clear from context.  
Replacement colour: `#8b949e` at full opacity on `#161b22` = **5.63:1** ✓

---

## 10. One Feature to Cut

**Cut: Era Exposure Statistics.**

The era stats panel (`📊 Era stats`, `renderEraStats()`) tracks how many times each named era has been displayed, computes a per-era exposure score, and ranks the 10 least-shown eras. This is a developer-built internal balancing mechanism that has been exposed to users as a feature, and it has three compounding UX problems:

1. **The vocabulary is opaque.** "Shown: 4 · Weight: 3 · Score: 1.33" means nothing to anyone who hasn't read `epochs.py`. The score is the ratio of exposure count to epoch weight — a concept that requires understanding the algorithm to interpret.

2. **The interaction path does not exist.** The panel gives the user information but no action. There is no "explore this era" button, no suggested years to navigate to, no direct consequence of seeing the data. A feature with no affordance for acting on its output is a dashboard in a dead-end room.

3. **It competes with the core loop.** The app's value is the moment-to-moment discovery: "What happened in year 1542?" The era stats panel asks users to think about their own viewing history in aggregate — a metacognitive task that breaks the discovery flow. The lightweight exposure-balancing effect (which is a backend concern) should remain in the algorithm invisibly; its output should influence which events are shown, not be surfaced as raw data.

**What to do instead of cutting entirely:** Replace the stats panel with a single sentence inside the year card, visible only when the current year triggers a rarely-seen era: *"You've rarely explored the Viking Age — want to?"* with a direct "Browse 793–1066" chip that navigates to a year in that range. This turns the algorithm's output into an actionable invitation rather than a raw readout.

---

## Summary — New Issues Beyond Round 1

Round 1 named the problems. Round 2 specifies the solutions. The five highest-value changes not covered in Round 1 detail:

1. **Onboarding as a layered tooltip sequence** anchored to real DOM elements with `pointer-events: none` — not a modal, not a full-screen splash. Keeps the clock live and visible while explaining.
2. **Live vs Browse mode rendered inside the year card itself** with a pulsing red LED and dashed-border distinction — not just a status text change in the nav row.
3. **Progressive disclosure of the Save feature** (hide until 3 events seen) prevents the "Saved (0)" cold-start confusion.
4. **Three concrete opacity-driven WCAG AA failures** in the dark theme — all fixable by removing opacity and using explicit hex colours.
5. **Era stats is the feature to cut** — it is a developer dashboard masquerading as a user feature, and its removal would simplify the mental model without reducing the app's core value.
