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
│   ├── epochs.py               # Språkbevisst laster for JSON-datafilene
│   ├── epochs.json             # 51 tidsaldre med engelske navn og datointervaller
│   ├── epochs.no.json          # 51 tidsaldre med norske navn
│   ├── era_context.json        # ~70 engelske erakontekstsetninger
│   ├── era_context.no.json     # ~70 norske erakontekstsetninger (østlandsk bokmål)
│   ├── future_events.json      # Kuraterte fremtidshendelser (engelsk)
│   └── future_events.no.json   # Kuraterte fremtidshendelser (norsk)
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

## Terminalversjoner *(arkivert)*

De opprinnelige terminalprototypene ligger i `_archived/` for referanse.  
De vedlikeholdes ikke og kan være utdaterte.

