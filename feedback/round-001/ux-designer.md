# Year Clock — UX Design Review · Round 1

**Reviewer:** Senior UX Designer (12 yrs, mobile/web product)  
**Artifact reviewed:** `clockapp/web/index.html` — single-file PWA  
**Date:** 2025  
**Scope:** Fundamentals audit — hierarchy, readability, interaction design, accessibility, mobile ergonomics

---

## 1. First Impression & Information Hierarchy

The page title — *"What Year Does It Look Like?"* — is rendered at `0.7rem` in muted uppercase. It is the first element in DOM order but it is visually almost invisible. This is a wasted opportunity. The concept behind this app is genuinely clever and playful, and the tagline *is* the concept, yet it is treated like a footnote.

The visual hierarchy on first load is:
1. Military time in huge monospace type (~4–7 rem, clamp)
2. Year card with the mapped year in teal
3. Event card with loading dots
4. Nav row (Prev · Live · Next)
5. Event card actions (Save, Like, Dislike, Saved)
6. Topic chips (below the fold on most phones)
7. Footer with "Era stats" link (barely visible)

This is **broadly correct** — the clock is primary, the year secondary, the fact tertiary. The hierarchy follows the conceptual model. However, the relationship between time and year is never explained. A new user watching `15:50` snap to year `1550` with a teal number might get it immediately, or might wonder why the app is showing random history facts and when they will change. There is zero onboarding copy anywhere on screen.

The era label (`eraLabel`) appears in very small muted text under the year number, and a separate `eraBadge` beneath it adds a second era name. Two stacked era labels at similar size create visual noise rather than signal — a user cannot tell which one is "the one that matters."

---

## 2. Clock Readability

**What works:** The military time display is excellent. `clamp(4rem, 20vw, 7rem)` scales beautifully across screen sizes, the monospace face (`SF Mono` / `Fira Code` fallback) reinforces the "precision instrument" feel, and `font-weight: 700` gives the digits authority. Showing seconds in a visually subordinate `0.45em` size on the same line is a smart detail — it communicates precision without competing with HH:MM.

**What doesn't:** The 12-hour time below (`0.9rem`, muted) is a useful secondary reference but it is redundant on most users' mental model. It occupies real estate that could be used for the "bridge" explanation. If it stays, it should be even more subtle — move it inside the clock block with lower opacity, not a standalone line.

The year display (`clamp(2.5rem, 14vw, 4.5rem)`) is in the same `year-color` as the accent colour everywhere else — teal `#39d0c8`. The pulse animation on minute-change is a lovely microinteraction. However the year label above it reads `"Current Year"` — technically wrong when the user has navigated away with Prev/Next. It should read `"Mapped Year"` or simply `"Year"` at all times, with the live-vs-viewing status living in the nav row (where it already does).

---

## 3. Topic Chip UX

**Discoverability:** Topic chips are below the fold on a 375pt viewport. A user who never scrolls will miss them entirely. Since topic filtering is the primary personalisation mechanic of the app, this is a meaningful discoverability failure.

**Active state:** The active chip uses `border-color: var(--accent)` + `background: var(--accent-dim)` — readable, but the dim teal fill is low-contrast against the dark card background. On a phone under bright light this reads as "almost-off" rather than "definitely on." Adding a `color: #fff` or increasing saturation of `--accent-dim` would help.

**Has-match / no-match indicators:** The `has-match` class appends a small `•` bullet (teal, `0.6rem`) after the chip label. This is subtle to the point of invisibility — a user will not understand what it means. The `no-match` class drops opacity to 0.4 and switches to a dashed border, which is more legible as a "not available" signal. However the asymmetry is confusing: chips either have a faint dot (match) or go dim and dashed (no-match), but there is no positive "available" state that feels intentionally active. Consider replacing the dot with a small coloured fill-dot before the emoji, or a chip background tint.

**Scrollability:** The chip row is horizontally scrollable with `scrollbar-width: none` — the scrollbar is hidden, so there is zero affordance that more chips exist to the right. A fade gradient on the right edge would be the standard solution.

**"+ Custom" chip:** Styled with a dashed border and accent colour, which differentiates it from topic chips visually. Good. But placing it at the end of a scrollable row means it is hidden by default. Users who want to add a custom topic must first discover they can scroll, then find the `+` button at the end. This should either be pinned (sticky within the scroll row), or given a more prominent entry point outside the chip row.

---

## 4. Event Card Design

The left-border accent stripe (`border-left: 3px solid var(--accent)`) gives the card a sense of categorisation — this convention is lifted from email clients and works here. The loading state (three bouncing dots) is clean and proportionate to card height.

**Fact readability:** `0.95rem` body text at `line-height: 1.6` is readable on desktop but pushes to the edge of comfortable on small phones where system font scaling is involved. The minimum 7rem card height (`min-height: 7rem`) is sometimes too small for longer Wikidata labels, causing text to overflow visually before the card expands. Testing with real Wikidata strings (some are 80-100 characters) reveals this more than testing with short strings.

**Action button placement:** The four action buttons (`★ Save`, `👍`, `👎`, `📋 Saved (n)`) all live in a horizontal row at the bottom of the event card. This cluster creates several problems:
- The `Saved` list button (📋) is functionally separate from the per-card actions (Save/Like/Dislike) — it opens a panel, not an action on the current event. Mixing navigation-level actions with card-level reactions in the same row is a category error.
- Tap targets are `0.3rem 0.7rem` padding on buttons that are already small — well below the 44×44pt WCAG minimum.
- `★ Save` and `👍` are visually very similar in weight and purpose. A user unfamiliar with the app cannot tell what the difference is without trial.

**Fallback text:** When no Wikidata results exist, the app shows the era description with a parenthetical `(Year YYYY falls within: Era1, Era2)`. This is functional but reads as a debug string. A friendlier copy: *"No specific records found for this year. It falls within the [Era Name] period — [brief era description]."*

---

## 5. Navigation UX

The Prev/Next year navigation is the most interaction-heavy feature beyond topic chips, yet it is styled identically to action buttons (`nav-btn` vs `action-btn` share the same visual language). The nav row sits *above* the event card, which breaks the natural read-order: the user would logically navigate (top), then read the result (below), then react to it (below that). This ordering is actually sensible.

**"Viewing YYYY ← Live" status:** The nav status text reads `Viewing 1203 • ← Live` with "← Live" rendered as a styled anchor. This is minimally legible but fragile:
- The anchor is dynamically injected HTML via `innerHTML` and a `setTimeout` to re-attach the click listener. This is a race condition waiting to fail on slow renders.
- `0.7rem` font-size for mode-status is too small to be scannable at a glance while navigating.
- There is no visual differentiation between "I am live" mode and "I have navigated away" mode at the level of the year card itself. The year card still shows `Current Year` as the label regardless.

**Missing: Return to Live button.** When the user navigates away, the only affordance to return is the tiny inline "← Live" link. A dedicated `Live` button in the nav row, visually distinct (perhaps a pulsing dot), would be far more discoverable.

---

## 6. Era Badge & Stats Panel

The `eraBadge` (bottom of the year card, `0.65rem`, accent colour) shows a single era name selected by the exposure-balance algorithm. This is one of the more sophisticated backend-of-the-frontend features in the app, but it surfaces as a tiny string that looks identical to the `yearEra` label two elements above it. Two era names in similar style stacked in the year card with no hierarchy clue is confusing.

**Stats panel:** Accessible only through a `0.65rem` anchor (`📊 Era stats`) buried in the footer at `opacity: 0.5`. This is arguably the most buried feature in the entire app. The era stats themselves (Shown / Weight / Score) display raw algorithm internals (`score: 0.25`) which are meaningful to the developer but opaque to an end user. If this feature survives a future design iteration, the data should be translated to user-friendly language: "You haven't explored the Viking Age much yet — here are some years to try."

---

## 7. Custom Topic Flow

The `+ Custom` chip opens a modal that is clean and well-constrained (max-width 400px, semi-transparent overlay). The two inputs — topic name and comma-separated keywords — are logical. The problem is that the user must supply keywords that will be matched against raw Wikidata event labels, without any guidance about what those labels look like. A first-time user typing `"Space Exploration"` with keywords `"spacecraft, NASA, launch"` might get zero matches for year `0957` (understandably), but also zero matches for `1969` if the Wikidata labels use different vocabulary. There is no feedback on how many events matched, or example label strings to calibrate expectations.

The error case where both name and keywords are required but the form submits silently if empty — `if (!name || !kwText) return;` — gives zero feedback. The form should show inline validation, not a silent no-op.

Once created, a custom chip is removed via a tiny `✕` (0.65rem) inside the chip itself. This is a destructive action on a 7×7pt tap target with no confirmation. A long-press or swipe-to-delete pattern would be more appropriate on mobile, or at minimum a confirmation toast.

---

## 8. Onboarding

There is none.

A user who installs this PWA cold sees: a large time, a four-digit number in teal, "Historical Event" in tiny caps, three loading dots, and a row of chip pills. The mapping between `15:50 → 1550` is the entire concept of the app and it is communicated by nothing except the coincidence that the user happens to look at the screen when both values are simultaneously visible.

Minimum viable onboarding would be a single sentence beneath the year card: *"Your clock reads 15:50 → that maps to the year 1550."* Alternatively, a one-time tooltip or a dismissible intro card on first launch. A welcome modal on first install is overkill; a subtitle is not.

The app title `"What Year Does It Look Like?"` is the only hint, and at `0.7rem` in muted uppercase it is not readable as a question — it is just barely visible decoration.

---

## 9. Mobile Ergonomics

**Thumb zones:** On a modern 390pt-wide iPhone, the comfortable single-thumb reach zone covers roughly the lower third of the screen. The app's layout stacks content top-to-bottom, pushing:
- Topic chips (frequently used) to the middle-lower zone — acceptable but not ideal
- Action buttons (Save/Like/Dislike) in the lower-middle portion of the card — passable
- The `+ Custom` chip to an unknown position at the end of a scrollable row — unreachable until scrolled

The nav row (Prev/Next) sits high, which is problematic for one-handed use. These buttons are likely used repeatedly during exploration sessions and belong in thumb-reach territory.

**Tap targets:** Multiple critical buttons fall below the 44×44pt WCAG/Apple HIG minimum:
- `action-btn`: `0.3rem 0.7rem` padding with `0.75rem` font → approx 30×28pt
- `nav-btn`: `0.3rem 0.8rem` with `0.8rem` font → approx 30×30pt  
- `chip-remove` (✕): `0.65rem` font inline in a chip → ~10×10pt — egregiously small

**Scroll behaviour:** The main content is a flex column centred in the viewport. On small phones this may not scroll at all (everything visible) or require scrolling to see topic chips. There is no explicit overflow-y or scroll anchoring, meaning if content overflows the viewport it just crops.

---

## 10. PWA Install Prompt

There is no handling of the `beforeinstallprompt` event. The app registers a service worker and includes a `manifest.json`, which enables the browser's default install prompt, but there is no in-app "Install this app" suggestion or explanation. On iOS Safari, `beforeinstallprompt` is not fired at all — the only install path is via the Share → Add to Home Screen menu, which the vast majority of users will never discover.

A first-time banner or tooltip ("📲 Add to your home screen for the best experience") — dismissible, non-blocking — would meaningfully increase adoption. The `theme-color` and apple meta tags are correctly set, so the install experience once triggered is polished.

---

## 11. Accessibility

**ARIA labels:** No `aria-label` attributes are present on any interactive element. Buttons labelled only with emoji (`👍`, `👎`, `✕`) have no accessible name. Screen reader users will hear "unlabelled button" for dislike and the chip remove actions.

**Keyboard navigation:** All interactive elements appear to be native `<button>` and `<a>` elements, so tab focus should work. However there are no visible focus styles defined — the browser default `:focus` ring may or may not be visible depending on OS/browser, and is not styled to the design system.

**Colour contrast:** The muted text colour `#8b949e` on `#0d1117` background yields a contrast ratio of approximately **4.5:1** — just barely passing WCAG AA for normal text, but borderline. The `footer` element applies an additional `opacity: 0.5` on top of this, pushing the effective contrast of the "Era stats" link to approximately **2.2:1** — failing WCAG AA for any text size. This is the most concrete accessibility failure in the build.

**Modal focus management:** When the custom topic modal opens (`customTopicModal.hidden = false`), focus is not moved inside the modal. Keyboard and assistive technology users will not know the modal has appeared. Focus should be trapped within the modal while it is open and returned to the trigger element on close.

**Colour as sole state indicator:** The `has-match` chip state is communicated only via a small colour dot; the `no-match` state via reduced opacity and dashed border. Neither has a textual or ARIA equivalent.

---

## 12. Animation & Transitions

**Year pulse:** The `yearPulse` keyframe (scale 1.0 → 1.08 → 1.0, opacity drop to 0.7) fires each minute when the mapped year changes. It is subtle, proportionate, and tied to a real event — excellent. The forced reflow hack (`void elYear.offsetWidth`) to re-trigger the CSS animation is a known-acceptable pattern.

**Event text fade:** The double `requestAnimationFrame` pattern to trigger the `.visible` opacity transition is correct and avoids the paint-before-transition race. The 0.5s ease transition is smooth.

**Topic chip re-render:** Chips are completely destroyed and re-created in the DOM on every render call (`row.innerHTML = ''` + `forEach`). This means no transition exists between topic states — the chip row flashes rather than transitions. With 8+ chips potentially changing state, the flash is noticeable. Using CSS classes to toggle state rather than full re-creation would enable proper transitions and avoid scroll position reset in the chip row.

**Body background transition:** `transition: background 0.6s ease` on `body` handles the teal↔purple theme switch for future years. This is a nice contextual detail.

**No reduced-motion respect:** None of the animations check for `@media (prefers-reduced-motion: reduce)`. The year pulse and event fade are minor, but this should be addressed.

---

## 13. Top 3 UX Wins

### Win 1: The Core Concept Is Executed Cleanly

The military-time-to-year mapping is novel and the visual result — large time, large year, a historical fact — is immediately comprehensible to users who work it out. The dark theme with the teal accent is polished and consistent. The app feels like a developer's thoughtful side project, not a prototype.

### Win 2: Topic Chip System Is Genuinely Useful

The combination of 8 pre-built topic filters with keyword-based matching, has-match indicators, and custom topic creation is a feature-rich personalisation system that is rare in apps of this scope. The fallback to "showing any" when no topic matches is graceful and avoids blank states. The persistence of the selected topic across sessions via `localStorage` is a small but significant quality-of-life detail.

### Win 3: The Dislike-to-Skip Feedback Loop

The `👎` dislike storing facts in localStorage and immediately rotating to the next event is a smooth, satisfying interaction. It solves a real problem (Wikidata returns irrelevant Wikidata entity names like "Q123456" patterns have been filtered, but some noise remains) and gives the user agency. The fact that disliked items are remembered and skipped in future cycles is thoughtful persistence that rewards repeat use.

---

## 14. Top 5 UX Issues — Ranked by Severity

### Issue 1 (Critical): No Onboarding — The Concept Is Invisible

**Severity:** Critical. Users who do not understand the `HH:MM → YYYY` mapping will see a history app with random changing facts and have no model for why the year changes, why there's a military clock, or what they're supposed to do.

**Fix:** Add a single descriptive subtitle near the clock block: *"Your military time maps to a year in history."* On first visit, show a one-time dismissible tooltip on the year card. This requires ~3 lines of HTML and ~10 lines of JS.

---

### Issue 2 (High): Tap Targets Are Too Small for Mobile

**Severity:** High. `action-btn` and `nav-btn` padding resolves to ~28–30pt buttons, the chip `✕` to ~10pt. These will generate systematic mis-taps on mobile, degrading the experience for the app's primary use context.

**Fix:** Set `min-height: 44px; min-width: 44px` on `action-btn`, `nav-btn`, and wrap the chip `✕` in a properly-padded `<button>` rather than an inline span.

---

### Issue 3 (High): Topic Chips Below the Fold with No Scroll Affordance

**Severity:** High. The primary personalisation feature is invisible to users who don't scroll, and the scrollable chip row gives no cue that content extends beyond the visible area.

**Fix:** Reposition the topic row immediately below the year card (above the nav row), so it is visible on first render on all common phone sizes. Add a right-edge fade gradient on `.topic-row::after` to indicate scrollability.

---

### Issue 4 (Medium): Footer "Era Stats" Link Is Inaccessible at `opacity: 0.5`

**Severity:** Medium (combines accessibility failure + feature burial).

**Fix:** Remove the `opacity: 0.5` from `.footer`. The `--text-muted` colour already provides sufficient visual de-emphasis without contrast failure. Move the era stats entry point to inside the year card (a subtle icon button in the card corner) where it is contextually logical.

---

### Issue 5 (Medium): "Current Year" Label is Wrong During Navigation + No Clear Live Mode Indicator

**Severity:** Medium. The `.year-label` text `"Current Year"` is factually wrong when the user has navigated to a historical year. Combined with the tiny nav-status text, there is no strong visual signal that the user is in "browsing" vs "live clock" mode.

**Fix:** Change the year label dynamically: `"Live Year"` in live mode, `"Viewing Year"` in navigate mode. Add a live indicator dot (animated pulse, like a recording LED) next to the clock or year when in live mode — a visual anchor that disappears when the user navigates away, making the mode switch immediately apparent.

---

## Summary Score

| Dimension | Score |
|---|---|
| Visual Design | 8/10 — strong dark theme, good type scale |
| Information Architecture | 6/10 — concept ordering good, feature burial bad |
| Interaction Design | 6/10 — clever mechanics, fragile tap targets |
| Accessibility | 4/10 — contrast failures, missing ARIA, no focus management |
| Onboarding | 2/10 — none |
| Mobile Ergonomics | 5/10 — content fits but targets are undersized |
| Animation Quality | 8/10 — smooth where applied, just needs reduced-motion |

**Overall: 6/10 — a solid foundation that needs ergonomic polish and a user model.**

---

*Round 2 should cover: loading states / error states (offline mode, Wikidata rate limits), the Flutter client parity, and performance on mid-range Android devices.*
