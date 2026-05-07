# Historieklokka — The History Clock

> *What year does it look like right now?*

A progressive web app (PWA) that maps the current military time to a historical year and displays a curated fact from that year. **15:23** shows something from **1523**. **09:07** shows something from **907**.

**Live at [historieklokka.no](https://historieklokka.no)**

---

## How It Works

| Clock time | Mapped year | Example fact |
|-----------|-------------|--------------|
| 09:07 | 907 | Edmund I becomes King of England |
| 15:23 | 1523 | Publication of Luther's *On Temporal Authority* |
| 19:69 | 1969 | Apollo 11 lands on the Moon |
| 23:59 | 2359 | Far future — contextual era text shown |

Each minute, the clock fetches a fact from [Wikidata](https://www.wikidata.org). Facts are cached server-side so subsequent visitors see instant results. An era-context layer adds vivid background sentences ("The Black Death was devastating Europe") for every year on the clock.

---

## Repository Structure

```
clockapp/
├── web/                # PWA front-end (single HTML file + service worker)
│   ├── index.html
│   └── sw.js
├── server/             # FastAPI backend
│   ├── main.py         # API routes
│   ├── fetcher.py      # Wikidata SPARQL queries + content filtering
│   ├── warmer.py       # Background cache warmer
│   ├── scorer.py       # Optional LLM quality scoring (OpenAI)
│   ├── db.py           # SQLite cache
│   ├── config.py       # Settings (env vars)
│   └── Dockerfile
├── data/
│   ├── era_context.json  # Vivid context sentences for every clock year
│   └── epochs.py         # Era lookup helpers
├── _archived/          # Superseded terminal and Flutter versions
├── docker-compose.yml          # Local development
├── docker-compose.prod.yml     # Production (Caddy + auto-HTTPS)
├── Caddyfile           # Caddy reverse proxy config
├── deploy.sh           # One-command deploy script
├── .env.example        # Configuration reference
└── SERVER-SETUP.md     # Server provisioning guide
```

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

Clear the fact cache on deploy (fetches fresh results with latest filters):

```bash
./deploy.sh root@YOUR_SERVER_IP --clear-cache
```

---

## Configuration

Copy `.env.example` to `.env` on the server and fill in your values.  
See `.env.example` for all available options, including the optional LLM scorer.

---

## Content Quality

Facts come from Wikidata SPARQL queries with multi-layer filtering:

1. **SPARQL-level exclusions** — asteroids, eclipses, natural numbers, disambiguation pages filtered out before they consume result slots
2. **Label filtering** — minimum length, must contain spaces, no bare Q-codes, regex patterns for boring entries
3. **Notability proxy** — post-1850 results require ≥ 20 Wikipedia sitelinks (cross-language presence)
4. **LLM scoring** *(optional)* — `gpt-4o-mini` re-ranks and filters results; enable with `OPENAI_API_KEY`

---

## Terminal Versions *(archived)*

The original terminal prototypes are kept in `_archived/` for reference.  
They are not maintained and may be out of date.

