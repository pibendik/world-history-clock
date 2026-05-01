# YearClock API

FastAPI backend for the "What Year Does It Look Like?" clock app.

## Setup

```bash
pip install -r clockapp/server/requirements.txt
```

## Run

```bash
uvicorn clockapp.server.main:app --port 8421 --reload
```

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Health check |
| GET | `/year/{year}` | Events + eras for a year |
| GET | `/year/{year}/buffer?window=2` | Prefetch ±window years |
| POST | `/reaction` | Like/dislike a fact |
| GET | `/reactions` | All reactions |
| GET | `/saved` | All saved facts |
| POST | `/saved` | Save a fact |
| DELETE | `/saved/{key}` | Remove a saved fact |
| GET | `/eras` | Era exposure stats |
