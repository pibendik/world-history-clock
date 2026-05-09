# Historieklokka — The History Clock

> *What year does it look like right now?*

A progressive web app (PWA) that maps the current military time to a historical year and displays a curated fact from that year. **15:23** shows something from **1523**. **09:07** shows something from **907**. **21:49** shows something from **2149** — which hasn't happened yet.

**Live at [historieklokka.no](https://historieklokka.no)**

**Primært for norske brukere** — the app is aimed at Norwegian users. UI localization to Norwegian is in progress.

---

## How It Works

| Clock time | Mapped year | Example fact |
|-----------|-------------|--------------|
| 09:07 | 907 | Edmund I becomes King of England |
| 15:23 | 1523 | Publication of Luther's *On Temporal Authority* |
| 19:69 | 1969 | Apollo 11 lands on the Moon |
| 20:29 | 2029 | *Future zone — see below* |
| 23:59 | 2359 | Far future — contextual era text shown |

Each minute, the clock fetches a fact from [Wikipedia](https://en.wikipedia.org). Facts are cached server-side so subsequent visitors see instant results. An era-context layer adds vivid background sentences ("The Black Death was devastating Europe") for every year on the clock.

---

## The Future Zone (2026–2359)

Once the clock passes **20:26** each day, it enters territory where no one has lived yet. The app handles this with a curated set of future events in `data/future_events.py` covering planned space missions, sci-fi imagined futures, and astronomical milestones — displayed with source attribution and a distinct visual style.

---

## Repository Structure

```
clockapp/
├── web/                # PWA front-end (single HTML file + service worker)
│   ├── index.html      # ~1000 lines: CSS, HTML, JS — clock + event card + reactions
│   └── sw.js
├── server/             # FastAPI backend
│   ├── main.py         # API routes (/now, /year/{year}, /debug/*)
│   ├── fetcher.py      # Wikipedia event fetching + content filtering
│   ├── warmer.py       # Background cache warmer (runs nightly 04:00 UTC)
│   ├── scorer.py       # LLM quality scoring (OpenAI gpt-4o-mini)
│   ├── db.py           # SQLite: event_cache, reactions, saved_facts, era_exposure
│   ├── config.py       # Settings (env vars)
│   └── Dockerfile
├── data/
│   ├── epochs.py           # 50+ named eras with date ranges + context sentences
│   └── future_events.py    # Curated future-zone events (fiction, astronomy, planned)
├── tests/              # pytest — 50 tests covering fetcher, epochs, year calculation
├── _archived/          # Superseded terminal and Flutter versions
├── docker-compose.yml          # Local development
├── docker-compose.prod.yml     # Production (Caddy + auto-HTTPS)
├── Caddyfile           # Caddy reverse proxy config
├── deploy.sh           # One-command deploy script
├── .env.example        # Configuration reference
└── SERVER-SETUP.md     # Server provisioning guide
```

---

## API

The backend exposes a simple public API. No authentication required.

**Current moment (what the clock shows right now):**
```bash
curl https://historieklokka.no/api/v1/now | jq .
```

**A specific year:**
```bash
curl https://historieklokka.no/api/v1/year/1969 | jq .
```

**Debug — raw Wikipedia events for a year:**
```bash
curl https://historieklokka.no/api/v1/debug/wikipedia?year=1066 | jq .
```

Full API docs: [https://historieklokka.no/docs](https://historieklokka.no/docs)

---

## Running Locally

**Prerequisites:** Docker + Docker Compose

```bash
git clone https://github.com/pibendik/world-history-clock.git
cd world-history-clock
docker compose up --build
```

Open [http://localhost:8421](http://localhost:8421) — the clock is live.  
API docs at [http://localhost:8421/docs](http://localhost:8421/docs).

---

## Deploying to Production

See **[SERVER-SETUP.md](SERVER-SETUP.md)** for full provisioning instructions.

Quick deploy after changes:

```bash
./deploy.sh root@YOUR_SERVER_IP
```

Clear the fact cache on deploy (re-fetches all years with latest filters):

```bash
./deploy.sh root@YOUR_SERVER_IP --clear-cache
```

---

## Configuration

Copy `.env.example` to `.env` on the server and fill in your values.  
See `.env.example` for all available options, including the LLM scorer (OpenAI).

---

## Content Pipeline

Facts come from Wikipedia year articles with a multi-layer pipeline:

1. **Wikipedia fetch** — `action=query&prop=revisions` with `redirects=1`; handles early year redirect articles (e.g. "701 AD" → "701"). Events section extracted via regex.
2. **Label filtering** — minimum length, no bare Q-codes, regex exclusions for sports seasons, astronomical catalog objects, Olympics participation entries, etc.
3. **LLM scoring** *(requires `OPENAI_API_KEY`)* — `gpt-4o-mini` re-ranks and selects the most interesting events; results stored in SQLite.
4. **Era-context fallback** — if no events are found for a year (very ancient or very sparse Wikipedia coverage), a vivid era description is shown instead. This is logged as a WARNING.

The cache warmer runs nightly at 04:00 UTC. It starts from the current hour so today's remaining hours are cached within minutes of a fresh deploy. Full warm takes ~1.5 hours (~4s/year including LLM scoring).

---

## Features

- ⏰ **Live clock** — updates every second; year changes every minute
- 📖 **Historical events** — from Wikipedia, LLM-scored for interest
- 🕰️ **Era context** — 50+ named historical eras with vivid descriptions
- ⬅️➡️ **Navigation** — arrow keys, prev/next buttons, timeline slider, click-to-set-time
- ☆ **Save facts** — bookmark events in localStorage (up to 200)
- ✕ **Dislike** — skip an event and hide it from future rotation
- 🔮 **Future zone** — curated events for years 2026–2359
- 📱 **PWA** — works as a home screen app on Android/iOS

---

## Language / Localization

**Primary audience: Norwegian users.** The app name "historieklokka" is Norwegian ("the history clock").

- UI chrome: currently English → **Norwegian (bokmål) translation is the next priority**
- Event text: English (from English Wikipedia) — acceptable for now
- Long-term: Norwegian Wikipedia (`no.wikipedia.org`) for fully Norwegian content
- English version: planned as a separate domain or language toggle

---

## Terminal Versions *(archived)*

The original terminal prototypes are kept in `_archived/` for reference.  
They are not maintained and may be out of date.

