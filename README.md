# What Year Does It Look Like?

A terminal clock that maps the current military time (HH:MM) to a year and
fetches an interesting historical fact about that year from Wikidata/Wikipedia.

## Examples

| Time  | Year |
|-------|------|
| 15:50 | 1550 |
| 09:07 | 907  |
| 00:00 | 0    |
| 23:59 | 2359 |

## Versions

### `clock_rich.py` — polished (requires `rich`)

Full-featured version with a live layout, color-coded eras, multiple events
stacked in a panel, spinner while fetching, and no-flicker updates.

```bash
pip install -r clockapp/requirements.txt
python3 clockapp/clock_rich.py
```

- **Future years** (> 2025): magenta colour scheme, labelled "THE FUTURE"
- **Antiquity** (< 100 AD): dim yellow, noted "sparse records"
- Up to **3 events** shown per year (from Wikidata, with Wikipedia / Numbers API fallback)
- Event data is re-fetched only when the mapped year changes (every minute)

### `clock.py` — simple (only requires `requests`)

Minimal ANSI version; no additional dependencies beyond `requests`.

```bash
pip install requests
python3 clockapp/clock.py
```

## Requirements

- Python 3.10+
- `requests` — HTTP calls to Wikidata / Wikipedia / Numbers API
- `rich` — only for `clock_rich.py`
- Internet connection
