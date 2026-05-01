# Ops & Deployment Review — YearClock API
**Round 001 · Reviewer: DevOps/SRE**

---

## 1. Current Deployment Story

A new developer needs to:

1. Clone the repo.
2. `cd` to the repo root (the `sys.path.insert` in `main.py` depends on running from there).
3. `pip install -r clockapp/server/requirements.txt` — into their global Python environment, or hope they remember to create a venv first (the `clockapp/venv/` directory exists in the repo but is not in `.gitignore` and is tracked, which is its own problem).
4. Run `uvicorn clockapp.server.main:app --port 8421 --reload`.
5. Separately, serve `clockapp/web/index.html` — either by double-clicking it, or with `python3 -m http.server 8080`.

There is no single "run this one command" entry point. No `Makefile`, no `docker compose up`, no `./start.sh`. The two pieces (API and PWA) start independently, through different instructions in two different README files. A new developer will spend time just wiring them together and figuring out that the web app's fetch calls need to hit `localhost:8421`.

**Day-one impact:** onboarding takes 20–30 minutes of detective work instead of 2 minutes. For a team or a CI machine, this is a reliability risk — different developers may have different Python versions, library versions, or forget a step entirely.

---

## 2. Missing Containerisation

There is no `Dockerfile`, no `docker-compose.yml`, no `.dockerignore`. The consequences are concrete:

- **Reproducibility is zero.** The service runs on "whatever Python 3.x is installed on this machine." The `requirements.txt` has no pinned versions (see §10), so `pip install` today may produce different results than `pip install` in three months.
- **The venv is committed to the repo.** `clockapp/venv/` contains compiled `.so` files and pip metadata — these are platform-specific and should never live in source control. This alone can cause subtle failures when someone on a different OS tries to use the checked-in venv.
- **No isolation.** The DB path is hardcoded to `~/.clockapp/yearclock.db` — the home directory of whichever user is running the process. In a container that maps a volume, this is fine. On a bare VM with multiple services, this is a naming collision waiting to happen.

**Minimum fix:** A two-stage `Dockerfile` (builder + slim runtime image) and a `docker-compose.yml` that wires the API container to a named volume for the SQLite file and serves the static PWA via an nginx sidecar. This collapses a 5-step manual process into `docker compose up`.

---

## 3. Process Management — `--reload` in Production

`uvicorn ... --reload` uses a file-system watcher (`watchfiles`) to restart the worker when source files change. In production this is wrong for several reasons:

- **It adds a watchdog subprocess** that consumes inotify handles and CPU for no benefit.
- **It restarts on *any* file change**, including log files, temp files, or a malicious write — a security concern.
- **It is single-process.** `uvicorn` without `--workers N` spawns exactly one worker. Under load, one slow Wikidata SPARQL call (which can take 2–4 seconds) blocks all other requests.
- **It does not gracefully drain connections** before restarting (the reload mechanism is not SIGTERM-safe).

**Production command should be:**
```bash
uvicorn clockapp.server.main:app \
  --host 0.0.0.0 \
  --port 8421 \
  --workers 2 \
  --no-access-log \
  --log-level warning
```

Or better: use **Gunicorn with the uvicorn worker class**, which gives proper pre-fork multiprocessing, graceful reload, and signal handling:
```bash
gunicorn clockapp.server.main:app \
  -k uvicorn.workers.UvicornWorker \
  -w 2 \
  --bind 0.0.0.0:8421
```

Note: If you switch to multiple workers, the SQLite WAL mode already enabled in `db.py` handles concurrent readers fine, but concurrent writes will serialize — acceptable for this workload, but worth knowing.

---

## 4. Static File Serving

The web app is a single `index.html` with no build step. That is actually a strength — it can be deployed anywhere. The question is where.

- **`python3 -m http.server`** is a development convenience, not a server. It has no caching headers, no compression, no HTTPS, no security headers (`Content-Security-Policy`, `X-Frame-Options`), and it will serve your entire file system if someone navigates `../`.
- **nginx** is the right answer for self-hosted. A 5-line config block, gzip on, `Cache-Control: max-age=86400`, and an `try_files` rule. If the API is also behind nginx, both can share a single HTTPS termination point, eliminating the cross-origin CORS wildcard (`allow_origins=["*"]`) that currently has to be there.
- **GitHub Pages / Netlify / Cloudflare Pages** are the right answer if you want zero ops for the frontend. Push `clockapp/web/index.html`, configure the publish directory, done. The static frontend then calls the API backend at a known URL. This is my recommendation: keep frontend hosting out of the backend deployment entirely.

**Current CORS wildcard** (`allow_origins=["*"]`) is a temporary workaround for local development. Once the frontend has a stable deployed URL, lock this down to that origin only.

---

## 5. Database Management

`_DB_PATH = Path.home() / ".clockapp" / "yearclock.db"` has several operational problems:

- **No explicit path configuration.** If you deploy as a Docker container, systemd service under a dedicated user, or a cloud VM, `~` is different in each case. The DB silently lands in different places.
- **No migration system.** The schema is applied via `CREATE TABLE IF NOT EXISTS` in `get_db()` on every connection. This pattern works for initial creation but cannot handle schema changes. If you add a column to `reactions`, existing deployments will not migrate — the new column just won't exist until someone manually runs `ALTER TABLE`. Use **Alembic** (already pairs well with SQLAlchemy) or at minimum a manual migration script with a `schema_version` table.
- **No backup.** SQLite supports `VACUUM INTO` for online backups. A nightly `sqlite3 ~/.clockapp/yearclock.db ".backup /backups/yearclock-$(date +%F).db"` run from cron or a systemd timer is the minimum viable backup strategy. With WAL mode enabled, hot backups are safe.
- **What happens on restart?** Nothing bad — SQLite is crash-safe with WAL. The data persists. But if someone accidentally deletes `~/.clockapp/`, all reactions, saved facts, and era exposure stats are gone permanently.
- **The event cache TTL** (7 days, hardcoded) is not configurable. This should be an environment variable.

---

## 6. Health Check Endpoint

```python
@app.get("/health")
def health():
    return {"status": "ok", "version": "1.0"}
```

This is a **liveness check only** — it confirms the process is running and the event loop is alive. It does not confirm the service is actually healthy. For a load balancer or Kubernetes readiness probe, you also want a **readiness check** that verifies:

1. **Database connectivity** — open a connection to `yearclock.db` and run `SELECT 1`.
2. **Schema presence** — confirm the expected tables exist (catches a botched migration).
3. Optionally: **last successful external fetch** (Wikidata) timestamp — if it's been >24h with no successful fetch, something is wrong.

Suggested improvement:
```python
@app.get("/health")
def health():
    try:
        conn = get_db()
        conn.execute("SELECT 1").fetchone()
        conn.close()
        db_status = "ok"
    except Exception as e:
        db_status = f"error: {e}"
    return {
        "status": "ok" if db_status == "ok" else "degraded",
        "version": "1.0",
        "db": db_status,
    }
```

The version should also come from a single source of truth (e.g., `importlib.metadata` or a `__version__` constant), not a hardcoded string that will drift.

---

## 7. Logging & Observability

Currently: nothing. No structured logging, no metrics, no tracing. Uvicorn writes plain-text access logs to stdout if `--no-access-log` is not set, but those are not structured and contain no application context.

**Minimum viable observability stack for this service:**

1. **Structured logging** — replace any `print()` statements with `logging` using `python-json-logger` to emit JSON. Key fields: `level`, `timestamp`, `message`, `year` (for year-fetch calls), `duration_ms`, `source` (wikidata/wikipedia/numbers). One line of context makes debugging 10× faster.

2. **Request duration logging** — add a FastAPI middleware that records request method, path, status code, and duration. This is 10 lines of code and tells you immediately if Wikidata is slow.

3. **Error tracking** — integrate **Sentry** (free tier covers this easily). Unhandled exceptions are captured automatically. The `sentry-sdk[fastapi]` integration is two lines.

4. **Metrics (optional but recommended)** — `prometheus-fastapi-instrumentator` adds a `/metrics` endpoint in 3 lines. Pair with a Grafana Cloud free tier for dashboards. Key metrics to watch: request rate, error rate, p95 latency on `/year/{year}`, cache hit/miss ratio.

5. **Tracing (later)** — OpenTelemetry traces for the Wikidata → Wikipedia → Numbers fallback chain would be valuable (it's a multi-hop external call with fallback logic), but this is not day-one work.

---

## 8. Environment Management

Current hardcoded values scattered across the codebase:
- Port: `8421` (in README, not even in the source)
- DB path: `~/.clockapp/yearclock.db` (in `db.py`)
- Cache TTL: `7 * 24 * 3600` (in `db.py`)
- `_CURRENT_YEAR = 2025` (in `main.py` — this will be wrong next January)
- CORS origins: `["*"]` (in `main.py`)

**What to do:** Create a `clockapp/server/config.py` using **Pydantic Settings** (`pydantic-settings`):

```python
from pydantic_settings import BaseSettings
from pathlib import Path

class Settings(BaseSettings):
    port: int = 8421
    db_path: Path = Path.home() / ".clockapp" / "yearclock.db"
    cache_ttl_seconds: int = 7 * 24 * 3600
    cors_origins: list[str] = ["*"]
    current_year: int = 2025

    class Config:
        env_prefix = "CLOCKAPP_"
        env_file = ".env"
```

This gives you: `.env` file support, environment variable overrides (`CLOCKAPP_PORT=9000`), type validation, and a single place to document all tunables. Zero magic.

**`_CURRENT_YEAR = 2025`** should be `datetime.date.today().year` — a hardcoded year is a ticking maintenance bug.

---

## 9. CI/CD

There is no CI configuration at all. Minimum viable GitHub Actions pipeline:

```yaml
# .github/workflows/ci.yml
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.12" }
      - run: pip install -r clockapp/server/requirements.txt pytest httpx
      - run: pytest clockapp/tests/ -v           # once tests exist
      - run: pip install ruff
      - run: ruff check clockapp/                # linting
  docker:
    needs: test
    if: github.ref == 'refs/heads/main'
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: docker/build-push-action@v5        # once Dockerfile exists
        with:
          push: true
          tags: ghcr.io/${{ github.repository }}:latest
```

Day-one minimum without tests or Docker: just the `ruff check` step. It takes 30 seconds and catches import errors, undefined names, and style drift before they hit production.

---

## 10. Dependency Pinning

`clockapp/server/requirements.txt`:
```
fastapi
uvicorn[standard]
requests
pydantic
```

All four are unpinned. This means:

- `pip install` today may install `fastapi==0.115.x`. In six months it installs `fastapi==0.120.x` with a breaking change. Your deploy breaks with no code change.
- Pydantic v1 → v2 was a breaking migration. If `pydantic` is unpinned and v3 ships, you will find out at deploy time.
- `requests` 2.x has had multiple security advisories. Unpinned means you may be running a vulnerable version without knowing.

**Fix:** Run `pip freeze > clockapp/server/requirements.lock` and use the lock file in CI and production. Keep `requirements.txt` for human-readable intent and `requirements.lock` for reproducible installs. Or switch to `uv` (faster, deterministic, excellent lock file support) — `uv lock` + `uv sync` replaces pip entirely.

---

## 11. Secrets Management

There are no secrets currently. But the likely roadmap includes:
- **Wikidata/Wikipedia API key** if rate limits become a problem.
- **OAuth tokens** if user accounts are added.
- **Sentry DSN** (semi-secret, but shouldn't be in source).

**Do not put secrets in `.env` files committed to git.** The pattern:

- Development: `.env` file, `.gitignore`'d, documented in `.env.example`.
- CI: GitHub Actions secrets (`secrets.SENTRY_DSN`), injected as env vars.
- Production (VM/bare metal): `/etc/clockapp/env` owned by root, readable only by the service user, loaded by the systemd unit via `EnvironmentFile=`.
- Production (Kubernetes): Kubernetes Secrets or Sealed Secrets; for more sensitive data, HashiCorp Vault or AWS Secrets Manager.

The Pydantic Settings approach from §8 handles all of these transparently — secrets arrive as environment variables regardless of source.

---

## 12. Crash Recovery

If `uvicorn` crashes, nothing restarts it. No supervisor, no systemd unit, no Docker restart policy. The service is simply down until someone notices.

**Three viable options, by deployment context:**

1. **systemd unit** (bare metal / VM, recommended for simplicity):
   ```ini
   [Service]
   ExecStart=/usr/bin/python3 -m gunicorn clockapp.server.main:app \
     -k uvicorn.workers.UvicornWorker -w 2 --bind 0.0.0.0:8421
   Restart=on-failure
   RestartSec=5s
   User=clockapp
   WorkingDirectory=/opt/clockapp
   EnvironmentFile=/etc/clockapp/env
   ```
   `systemctl enable clockapp` and it survives reboots, restarts on crash, logs to journald.

2. **Docker restart policy**: `restart: unless-stopped` in `docker-compose.yml`. Trivial to add, and Docker's own restart backoff prevents crash loops from hammering the system.

3. **Supervisor / PM2**: heavier than needed for a single Python process. Use systemd instead.

The Gunicorn + systemd combination is what I'd reach for on day one for a single-server deploy.

---

## 13. Top 5 Ops Improvements — Ranked by Urgency

These are the changes I would make on **day one of owning this service**, in order:

### 🔴 #1 — Add a Dockerfile and `docker-compose.yml`
This single change eliminates the reproducibility problem, the venv-in-git problem, the DB path problem, the process management problem, and the crash recovery problem *simultaneously*. A `docker-compose.yml` with a `restart: unless-stopped` policy, a named volume for the SQLite file, and an nginx service for the static frontend is ~50 lines and unlocks every other improvement.

### 🔴 #2 — Pin all dependencies
Run `pip freeze` and commit a lock file today. This is a 2-minute fix that prevents a class of "it worked yesterday" incidents. Unpinned deps are a latent production incident.

### 🟠 #3 — Add a `.env`-based config via Pydantic Settings
Replace the four hardcoded values (`port`, `db_path`, `CORS origins`, `_CURRENT_YEAR`) with a Settings class. Fix `_CURRENT_YEAR` to use `datetime.date.today().year`. This unblocks deployment to any environment without source code changes.

### 🟠 #4 — Add structured logging + Sentry
Add `python-json-logger` and `sentry-sdk[fastapi]`. This is ~10 lines of code and means that when the service misbehaves in production, you have evidence. Without this, debugging is `ssh` + `grep` in uvicorn stdout — painful and often too late.

### 🟡 #5 — Add a minimal GitHub Actions CI pipeline
Even without tests, a `ruff check` + `docker build` step on every push catches import errors and dependency installation failures before they reach production. Tests can be added incrementally; the pipeline structure should exist from the start.

---

## Summary Assessment

The YearClock API is well-structured internally — clean FastAPI layout, good separation of DB/fetcher/routes, WAL mode on SQLite, a health endpoint, and a no-dependency frontend. The bones are solid.

The operational story is effectively "run these two commands manually on your laptop." For a personal project that's fine. For anything that needs to be reliable, shared, or handed off, the gap between "it runs locally" and "it runs in production" is significant. None of the gaps are hard to close — they are all standard, well-understood patterns. The priority order above is designed to give maximum reliability improvement per hour of work invested.
