# Historieklokka — Historieklokkа

> *Hvordan ser klokken ut som et årstall?*

En progressiv nettapp (PWA) som oversetter nåværende klokkeslett til et historisk årstall og viser en kuriert hendelse fra det året. **15:23** viser noe fra **1523**. **09:07** viser noe fra **907**. **21:49** viser noe fra **2149** — som ennå ikke har skjedd.

**Live på [historieklokka.no](https://historieklokka.no)**

Primært for norske brukere. Engelsk versjon planlagt som separat domene (`YEARCLOCK_LANG=en`).

---

## Slik fungerer det

| Klokkeslett | Årstall | Eksempel |
|-------------|---------|---------|
| 09:07 | 907 | Æthelstan blir Englands første enekonge |
| 15:23 | 1523 | Luther utgir *Om verdslig øvrighet* |
| 19:69 | 1969 | Apollo 11 lander på Månen |
| 20:29 | 2029 | *Fremtidssone — se nedenfor* |
| 23:59 | 2359 | Fjern fremtid — tidsaldertekst vises |

Hvert minutt henter appen en hendelse fra [Wikipedia](https://en.wikipedia.org). Hendelsene bufres server-side, så påfølgende besøkende får umiddelbare svar. Et erakontekst-lag legger til levende bakgrunnssetninger for hvert årstall på klokken.

---

## Fremtidssonen (2026–2359)

Når klokken passerer **20:26** hver dag, beveger den seg inn i territorium ingen har levd i ennå. Appen håndterer dette med et kurert sett av fremtidshendelser i `data/future_events.json` (og `data/future_events.no.json` for norsk) — astronomiske begivenheter, planlagte romoppdrag, og fremtider fra science fiction — vist med kildehenvisning og eget visuelt uttrykk.

---

## Struktur

```
clockapp/
├── web/                        # PWA front-end
│   ├── index.html              # CSS, HTML, JS — klokke + hendelseskort + reaksjoner
│   └── sw.js                   # Service worker (offline-støtte)
├── server/                     # FastAPI-backend
│   ├── main.py                 # API-ruter: /now, /year/{year}, /config, /debug/*
│   ├── fetcher.py              # Wikipedia-henting + innholdsfiltrering
│   ├── warmer.py               # Bakgrunnsbuffer-varmer (kjører 04:00 UTC nightly)
│   ├── scorer.py               # LLM-kvalitetsscoring (OpenAI gpt-4o-mini)
│   ├── db.py                   # SQLite: event_cache, reactions, saved_facts, era_exposure
│   ├── config.py               # Innstillinger (miljøvariabler med YEARCLOCK_-prefiks)
│   └── Dockerfile
├── data/
│   ├── epochs.py               # Language-aware loader for JSON data files
│   ├── epochs.json             # 51 eras with English names and date ranges
│   ├── era_context.json        # ~70 English era context sentences
│   └── future_events.json      # Curated future events (2026–2359)
├── tests/                      # pytest — 50 tester
├── _archived/                  # Utdaterte terminal- og Flutter-versjoner
├── docker-compose.yml          # Lokal utvikling
├── docker-compose.prod.yml     # Produksjon (Caddy + auto-HTTPS)
├── Caddyfile                   # Caddy reverse proxy-konfig
├── deploy.sh                   # Én-kommando-deploy
├── .env.example                # Konfigurasjonsreferanse
└── SERVER-SETUP.md             # Serveroppsett
```

---

## API

Ingen autentisering kreves.

```bash
# Hva viser klokken akkurat nå?
curl https://historieklokka.no/api/v1/now | jq .

# Et spesifikt årstall:
curl https://historieklokka.no/api/v1/year/1969 | jq .

# Frontend-konfig (språk + tidsalderliste):
curl https://historieklokka.no/api/v1/config | jq .

# Rådata fra Wikipedia (debug):
curl https://historieklokka.no/api/v1/debug/wikipedia?year=1066 | jq .
```

Full API-dokumentasjon: [https://historieklokka.no/docs](https://historieklokka.no/docs)

---

## Kjøre lokalt

**Forutsetninger:** Docker + Docker Compose

```bash
git clone https://github.com/pibendik/world-history-clock.git
cd world-history-clock/clockapp
docker compose up --build
```

Åpne [http://localhost:8421](http://localhost:8421).  
API-docs: [http://localhost:8421/docs](http://localhost:8421/docs).

---

## Produksjonsdeploy

Se **[SERVER-SETUP.md](SERVER-SETUP.md)** for full serveroppsett.

```bash
# Vanlig deploy:
./deploy.sh root@SERVER_IP

# Deploy med cache-tømming (re-henter alle år med nye filtre):
./deploy.sh root@SERVER_IP --clear-cache
```

---

## Konfigurasjon

Kopier `.env.example` til `.env` på serveren. Viktige variabler:

| Variabel | Standard | Beskrivelse |
|----------|----------|-------------|
| `OPENAI_API_KEY` | — | Påkrevd for LLM-scoring |
| `YEARCLOCK_LLM_SCORING` | `false` | Skru på LLM-scoring |
| `YEARCLOCK_LANG` | `en` | `no` for norsk, `en` for engelsk |
| `YEARCLOCK_DB_PATH` | `~/.clockapp/yearclock.db` | SQLite-filplassering |

---

## Innholdspipeline

1. **Wikipedia-henting** — `action=query&prop=revisions` med `redirects=1`; håndterer tidlige årtalls-omdirigeringsartikler (f.eks. «701 AD» → «701»). Hendelsesseksjonen ekstraheres med regex.
2. **Etikett-filtrering** — minimumslengde, ingen bare Q-koder, regex-eksklusjoner for sportssesonger, astronomiske katalogoppføringer, OL-deltakelsesoppføringer m.m.
3. **LLM-scoring** *(krever `OPENAI_API_KEY`)* — `gpt-4o-mini` rangerer og velger de mest interessante hendelsene; skrives om til levende prosa. For norsk (`YEARCLOCK_LANG=no`) brukes en arkivnorsk prompt med østlandsk bokmål-stil. Resultater lagres i SQLite.
4. **Erakontekst-fallback** — hvis ingen hendelser finnes for et år (svært gammelt eller sparsomt Wikipedia-dekning), vises en levende erabeskrivelse i stedet. Dette logges som WARNING.

Buffervarmeren kjører nightly kl. 04:00 UTC. Den starter fra nåværende time, slik at dagens gjenværende timer bufres innen minutter etter en fersk deploy. Full opplading tar ~1,5 time (~4s/år inkl. LLM-scoring).

---

## Funksjoner

- ⏰ **Live-klokke** — oppdateres hvert sekund; årstall endres hvert minutt
- 📖 **Historiske hendelser** — fra Wikipedia, LLM-scoret for interesse
- 🕰️ **Erakontekst** — 50+ navngitte historiske tidsaldre med levende beskrivelser
- ⬅️➡️ **Navigasjon** — piltaster, forrige/neste-knapper, tidslinjevelger, klikk-for-å-sette-tid
- ☆ **Lagre fakta** — bokmerk hendelser i localStorage (opptil 200)
- ✕ **Misliker** — hopp over en hendelse og skjul den fra fremtidig rotasjon
- 🔮 **Fremtidssone** — kuraterte hendelser for årstall 2026–2359
- 📱 **PWA** — fungerer som hjemskjermapp på Android/iOS

---

## Språk og lokalisering

**Primærmålgruppe: norske brukere.**

- UI: norsk bokmål
- Hendelsestekst: norsk bokmål (skrevet av LLM med østlandsk stil-prompt)
- Fremtidshendelser: norsk bokmål (`data/future_events.no.json`)
- Erakontekst: norsk bokmål (`data/era_context.no.json`)
- Engelsk versjon: planlagt som separat domene med `YEARCLOCK_LANG=en`; all infrastruktur er klar

---

## Ops Runbook

Quick reference for keeping the production server healthy.

### Check logs

```bash
ssh root@77.42.120.231
cd /opt/historieklokka

# Live API logs
docker compose -f docker-compose.prod.yml logs -f api

# Live Caddy (access + TLS) logs
docker compose -f docker-compose.prod.yml logs -f caddy

# Structured access log (JSON)
tail -f /var/log/caddy/access.log | jq .
```

### Restart services

```bash
ssh root@77.42.120.231
cd /opt/historieklokka

docker compose -f docker-compose.prod.yml restart api
docker compose -f docker-compose.prod.yml restart caddy
```

### Rollback

```bash
ssh root@77.42.120.231
cd /opt/historieklokka

git log --oneline -10          # find the commit to roll back to
git checkout <commit-sha>      # detached HEAD — site runs old code
docker compose -f docker-compose.prod.yml up -d --build api caddy

# To return to latest main:
git checkout main && git pull
docker compose -f docker-compose.prod.yml up -d --build api caddy
```

### Force cache clear (re-fetch all years from Wikipedia)

```bash
# From local machine — redeploys and flushes SQLite event cache:
./deploy.sh root@77.42.120.231 --clear-cache

# Or on the server directly:
ssh root@77.42.120.231
cd /opt/historieklokka
docker compose -f docker-compose.prod.yml exec api python -c \
  "from clockapp.server.db import get_db; db=next(get_db()); db.execute('DELETE FROM event_cache'); db.commit()"
docker compose -f docker-compose.prod.yml restart api
```

### Check OpenAI spend

1. Go to [platform.openai.com/usage](https://platform.openai.com/usage)
2. Model: `gpt-4o-mini` — typical cost is a few cents per day
3. Set a **hard monthly limit** at platform.openai.com/account/limits to cap surprise costs

### Health check

```bash
curl https://historieklokka.no/health
# Expected: {"status":"ok"}
```

### Rate limit hits (HTTP 429)

Caddy returns 429 when a single IP exceeds 30 req/min on `/api/*` or 120 req/min on static files. Check access log:

```bash
cat /var/log/caddy/access.log | jq 'select(.status==429)'
```

---


De opprinnelige terminalprototypene ligger i `_archived/` for referanse.  
De vedlikeholdes ikke og kan være utdaterte.

