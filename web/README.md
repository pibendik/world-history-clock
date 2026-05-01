# What Year Does It Look Like? — Web App

A single-page clock that maps military time `HH:MM → year`.  
**15:50** → you're in **1550**. Fetches real historical events from Wikidata/Wikipedia.

## Open it

Just open `index.html` in any modern browser — no build step, no dependencies.

```bash
# Serve locally (recommended, avoids some CORS edge cases):
python3 -m http.server 8080
# Then open http://localhost:8080
```

Or double-click `index.html` directly.

## How it works

| Feature | Detail |
|---|---|
| Clock | Updates every second via `setInterval` |
| Year mapping | `HH:MM` digits read as a 4-digit year |
| Events | Fetched from Wikidata SPARQL (primary) → Wikipedia REST (fallback) |
| Refresh | New event fetched once per minute (when the year digit changes) |
| Future years | `> 2025` shown with purple accent, no event fetch |
| Antiquity | `< 100 AD` shown with amber/sepia tint |

## Files

```
clockapp/web/
├── index.html   # Entire app — HTML + CSS + JS, no dependencies
└── README.md    # This file
```
