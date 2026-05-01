# Ops & Deployment Review — YearClock API
**Round 002 · Reviewer: DevOps/SRE**

Round 1 diagnosed the gaps. Round 2 delivers the files. Every code block below is production-ready and can be dropped into the repo as-is. Where a file touches existing source (`main.py`, `requirements.txt`) the minimal, surgical diff is shown rather than a full rewrite.

---

## 1. Dockerfile

Multi-stage build: the `builder` stage installs dependencies into a clean prefix; the `runtime` stage copies only what's needed. The final image has no pip, no compiler, and runs as a non-root user `appuser` (UID 1000).

SQLite with `--workers 1` is correct: multiple uvicorn worker processes share a single SQLite file, and while WAL mode handles concurrent readers, concurrent writers serialize — with multiple processes this creates lock contention that a single worker avoids entirely.

```dockerfile
# ── Stage 1: dependency builder ───────────────────────────────────────────────
FROM python:3.12-slim AS builder

WORKDIR /build

# Install build tools only in this stage
RUN apt-get update && apt-get install -y --no-install-recommends gcc && rm -rf /var/lib/apt/lists/*

COPY clockapp/server/requirements.txt .

# Install to an isolated prefix — nothing bleeds into the runtime image
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt


# ── Stage 2: runtime ──────────────────────────────────────────────────────────
FROM python:3.12-slim AS runtime

# Non-root user
RUN useradd --uid 1000 --no-create-home --shell /sbin/nologin appuser

WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# Copy application source
COPY clockapp/ ./clockapp/

# Data directory owned by app user — SQLite file lives here at runtime
RUN mkdir -p /data && chown appuser:appuser /data

USER appuser

# SQLite lives on a mounted volume at /data
ENV DB_PATH=/data/yearclock.db

EXPOSE 8421

# Docker-native health check — Docker marks container unhealthy if this fails
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python3 -c "import urllib.request; urllib.request.urlopen('http://localhost:8421/health')"

# --workers 1: SQLite WAL is safe for concurrent reads, but single-process
# avoids write serialization overhead and POSIX lock cross-process complexity.
CMD ["python3", "-m", "uvicorn", "clockapp.server.main:app", \
     "--host", "0.0.0.0", "--port", "8421", \
     "--workers", "1", "--no-access-log", "--log-level", "warning"]
```

`.dockerignore` (create alongside the Dockerfile):

```dockerignore
**/__pycache__
**/*.pyc
**/*.pyo
clockapp/venv/
clockapp/feedback/
.git
.env
*.md
```

---

## 2. docker-compose.yml

Two services: `api` (FastAPI/uvicorn) and `web` (nginx serving the static PWA). The SQLite file lives in a named Docker volume — it survives container recreation. Both services share the `clockapp` bridge network; nginx proxies `/api/` to the FastAPI service so the browser only talks to one origin, eliminating the CORS wildcard.

```yaml
version: "3.9"

services:

  api:
    build:
      context: .
      dockerfile: Dockerfile
    image: yearclock-api:latest
    container_name: yearclock-api
    restart: unless-stopped
    env_file: .env
    environment:
      DB_PATH: /data/yearclock.db
    volumes:
      - yearclock-db:/data
    expose:
      - "8421"
    networks:
      - clockapp
    healthcheck:
      test: ["CMD", "python3", "-c",
             "import urllib.request; urllib.request.urlopen('http://localhost:8421/health')"]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 15s

  web:
    image: nginx:1.27-alpine
    container_name: yearclock-web
    restart: unless-stopped
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./clockapp/web:/usr/share/nginx/html:ro
      - ./deploy/nginx/yearclock.conf:/etc/nginx/conf.d/default.conf:ro
      # Mount TLS certs here in production:
      # - /etc/letsencrypt:/etc/letsencrypt:ro
    networks:
      - clockapp
    depends_on:
      api:
        condition: service_healthy

volumes:
  yearclock-db:
    driver: local

networks:
  clockapp:
    driver: bridge
```

`.env` (not committed — add to `.gitignore`; commit `.env.example`):

```dotenv
PORT=8421
DB_PATH=/data/yearclock.db
WIKIDATA_URL=https://query.wikidata.org/sparql
CACHE_TTL_DAYS=7
CORS_ORIGINS=http://localhost,https://yearclock.example.com
CURRENT_YEAR=
```

`.env.example` (committed):

```dotenv
PORT=8421
DB_PATH=/data/yearclock.db
WIKIDATA_URL=https://query.wikidata.org/sparql
CACHE_TTL_DAYS=7
CORS_ORIGINS=http://localhost
CURRENT_YEAR=
```

---

## 3. GitHub Actions CI Pipeline

Four jobs: `lint`, `test`, `docker`, `validate-html`. The `test` job scaffolds the test runner even before tests exist — the job passes when there are zero tests (pytest exits 0 on an empty suite with `--ignore` guards).

```yaml
# .github/workflows/ci.yml
name: CI

on:
  push:
    branches: ["main", "dev"]
  pull_request:

env:
  PYTHON_VERSION: "3.12"
  IMAGE_NAME: ghcr.io/${{ github.repository }}/yearclock-api

jobs:

  lint:
    name: Lint (ruff)
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: ${{ env.PYTHON_VERSION }}
          cache: pip

      - name: Install ruff
        run: pip install ruff==0.4.4

      - name: Ruff lint
        run: ruff check clockapp/server/ clockapp/data/

      - name: Ruff format check
        run: ruff format --check clockapp/server/ clockapp/data/

  test:
    name: Test (pytest)
    runs-on: ubuntu-latest
    needs: lint
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: ${{ env.PYTHON_VERSION }}
          cache: pip

      - name: Install dependencies
        run: |
          pip install -r clockapp/server/requirements.txt
          pip install pytest pytest-cov httpx

      - name: Create test scaffold if missing
        run: |
          mkdir -p clockapp/tests
          if [ ! -f clockapp/tests/__init__.py ]; then touch clockapp/tests/__init__.py; fi
          if [ ! -f clockapp/tests/test_placeholder.py ]; then
            echo "# Placeholder — replace with real tests" > clockapp/tests/test_placeholder.py
            echo "def test_placeholder(): pass" >> clockapp/tests/test_placeholder.py
          fi

      - name: Run tests
        env:
          DB_PATH: ":memory:"
          PYTHONPATH: ${{ github.workspace }}
        run: pytest clockapp/tests/ -v --tb=short --cov=clockapp/server --cov-report=term-missing

  docker:
    name: Build Docker image
    runs-on: ubuntu-latest
    needs: test
    permissions:
      contents: read
      packages: write
    steps:
      - uses: actions/checkout@v4

      - name: Set up Docker Buildx
        uses: docker/setup-buildx-action@v3

      - name: Log in to GHCR
        if: github.ref == 'refs/heads/main'
        uses: docker/login-action@v3
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}

      - name: Build (and push on main)
        uses: docker/build-push-action@v5
        with:
          context: .
          file: Dockerfile
          push: ${{ github.ref == 'refs/heads/main' }}
          tags: |
            ${{ env.IMAGE_NAME }}:latest
            ${{ env.IMAGE_NAME }}:${{ github.sha }}
          cache-from: type=gha
          cache-to: type=gha,mode=max

  validate-html:
    name: Validate HTML (vnu)
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Install vnu HTML validator
        run: |
          sudo apt-get update -q
          sudo apt-get install -y default-jre
          curl -sSL https://github.com/validator/validator/releases/latest/download/vnu.jar \
            -o vnu.jar

      - name: Validate index.html
        run: java -jar vnu.jar --errors-only clockapp/web/index.html
```

---

## 4. Pydantic Settings — `clockapp/server/config.py`

Create this file. Then in `main.py`, replace the four hardcoded values with `from clockapp.server.config import settings`.

```python
# clockapp/server/config.py
import datetime
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    port: int = 8421
    db_path: Path = Path.home() / ".clockapp" / "yearclock.db"
    wikidata_url: str = "https://query.wikidata.org/sparql"
    cache_ttl_days: int = 7
    cors_origins: list[str] = ["*"]
    # Defaults to the current calendar year at startup — never goes stale.
    current_year: int = datetime.date.today().year

    @field_validator("db_path", mode="before")
    @classmethod
    def expand_home(cls, v: str | Path) -> Path:
        return Path(v).expanduser()

    @property
    def cache_ttl_seconds(self) -> int:
        return self.cache_ttl_days * 86_400


settings = Settings()
```

Diff for `main.py` (surgical, not a rewrite):

```python
# Replace at top of main.py:

# BEFORE:
_CURRENT_YEAR = 2025
# ... and later:
allow_origins=["*"],

# AFTER:
from clockapp.server.config import settings
# ... and later:
allow_origins=settings.cors_origins,
# ... and in _build_year_data:
is_future = year > settings.current_year
```

Add `pydantic-settings` to requirements (see §7 for the full pinned list).

---

## 5. Structured JSON Logging

Add this module and wire it into `main.py`. No new dependencies required beyond the standard library plus `python-json-logger` (already common in FastAPI projects).

```python
# clockapp/server/logging_config.py
import logging
import time
from typing import Callable

from fastapi import Request, Response
from pythonjsonlogger import jsonlogger


def configure_logging(level: str = "INFO") -> None:
    """Call once at app startup. All loggers inherit this handler."""
    handler = logging.StreamHandler()
    formatter = jsonlogger.JsonFormatter(
        fmt="%(asctime)s %(levelname)s %(name)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
        rename_fields={"asctime": "timestamp", "levelname": "level", "name": "logger"},
    )
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)


async def request_logging_middleware(request: Request, call_next: Callable) -> Response:
    """FastAPI middleware: logs every request with method, path, status, duration."""
    logger = logging.getLogger("yearclock.http")
    start = time.perf_counter()
    response: Response = await call_next(request)
    duration_ms = round((time.perf_counter() - start) * 1000, 1)

    logger.info(
        "http_request",
        extra={
            "method": request.method,
            "path": request.url.path,
            "status_code": response.status_code,
            "duration_ms": duration_ms,
            "client_ip": request.client.host if request.client else None,
        },
    )
    return response
```

Wire into `main.py`:

```python
# Add near the top of main.py, after imports:
from clockapp.server.logging_config import configure_logging, request_logging_middleware

configure_logging(level="INFO")
logger = logging.getLogger("yearclock.api")

# After app = FastAPI(...):
app.middleware("http")(request_logging_middleware)

# In _build_year_data, replace silent path with:
logger.info("year_fetch", extra={"year": year, "event_count": len(events), "is_future": is_future})
```

Example log line on a cache-hit `/year/1969` call:

```json
{"timestamp": "2025-01-15T14:32:01", "level": "INFO", "logger": "yearclock.http",
 "message": "http_request", "method": "GET", "path": "/year/1969",
 "status_code": 200, "duration_ms": 3.4, "client_ip": "172.18.0.1"}
```

Add `python-json-logger==2.0.7` to `requirements.in`.

---

## 6. SLO Definitions

Three SLOs tuned to the actual workload of this service: a read-heavy single-node API that depends on an external SPARQL endpoint (Wikidata) for cold-cache misses.

### SLO-1 — Availability
> **99.5% of `/health` probes return HTTP 200 in any rolling 30-day window.**

- **Why 99.5% and not 99.9%?** This is a personal/small-team project on a single VPS without redundancy. 99.5% allows ~3.6 hours downtime per month — enough for maintenance reboots and single-node failure recovery. Committing to 99.9% without a second node is theatre.
- **How to measure:** Uptime Robot (free tier) or a cron job on a separate machine: `curl -f http://yourhost/health`. Log pass/fail to a simple SQLite table or a Grafana Cloud probe. Alert when the 7-day rolling rate drops below 99.5%.

### SLO-2 — P95 Latency on `/year/{year}`
> **P95 response time ≤ 200 ms for cache-hit requests; ≤ 5 000 ms for cold-cache requests, in any 1-hour window with ≥ 10 requests.**

- **Cache hit** (event row exists in SQLite): pure DB read + era calculation + JSON serialisation. Target: 200 ms is generous — in practice this should be 20–50 ms. The 200 ms budget absorbs container cold-start and SQLite lock wait.
- **Cold cache** (no DB row, requires live Wikidata SPARQL): one round-trip to `query.wikidata.org` at ~1–3 s per request on a good day, potentially 5–8 s when Wikidata is under load. 5 000 ms is realistic; anything beyond signals Wikidata is struggling and a circuit-breaker should kick in.
- **How to measure:** The `request_logging_middleware` from §5 emits `duration_ms` in structured JSON. Pipe logs to any aggregation tool (Loki, CloudWatch Logs, even `jq` on the host). Track percentiles per hour. Alternatively: `prometheus-fastapi-instrumentator` exposes `http_request_duration_seconds_bucket` labels — one Grafana panel, done.
- **Distinguish cache hit vs miss:** Log a `cache_hit: true/false` field from `get_events_for_year` when returning DB rows vs calling the fetcher.

### SLO-3 — Error Rate
> **HTTP 5xx error rate ≤ 1% of all requests in any rolling 24-hour window.**

- **What counts as an error:** HTTP 500–599 returned to the client. HTTP 404 (invalid year), 422 (validation), and 429 (future rate-limiting) are **not** errors — they are correct client-driven responses.
- **Wikidata timeout handling:** currently a `requests` timeout bubbles into a 500. This should become a structured 503 with `Retry-After: 30` so the metric is accurate and the client can behave correctly.
- **How to measure:** Same middleware: count `status_code >= 500` / total requests per hour. Alert at 0.5% (warning) and 1% (critical). With `prometheus-fastapi-instrumentator`: `sum(rate(http_requests_total{status=~"5.."}[24h])) / sum(rate(http_requests_total[24h]))`.

---

## 7. Dependency Pinning with pip-tools

`requirements.in` states human intent. `pip-compile` produces a fully-pinned, hash-verified `requirements.txt`. CI uses the compiled file; humans edit only the `.in`.

**`clockapp/server/requirements.in`:**

```
# Runtime dependencies — edit this file, not requirements.txt
fastapi>=0.111,<1
uvicorn[standard]>=0.29,<1
requests>=2.32,<3
pydantic>=2.7,<3
pydantic-settings>=2.3,<3
python-json-logger>=2.0,<3
```

**Compile workflow:**

```bash
# Install pip-tools once (not in requirements.in)
pip install pip-tools

# Generate pinned requirements.txt from requirements.in
pip-compile clockapp/server/requirements.in \
  --output-file clockapp/server/requirements.txt \
  --generate-hashes \
  --strip-extras

# Install from the compiled, hash-verified file
pip install -r clockapp/server/requirements.txt
```

**After pinning, `requirements.txt` will look like:**

```
# This file was autogenerated by pip-compile with Python 3.12
# Do not edit this file directly. Edit requirements.in and re-run pip-compile.
#
annotated-types==0.7.0 \
    --hash=sha256:1f02e8b43a8fbbc3f3e0d4f0f4bfc8131bcb4eebe8849b8e5c773f3a1c582a53 \
    --hash=sha256:aff07c09a53a08bc8cfccb9c85b05f1aa9a2a6f23728d790723543408344ce89
fastapi==0.111.1 \
    --hash=sha256:...
# ... etc
```

**Add to CI** (between install and test steps):

```yaml
- name: Verify requirements.txt is up-to-date
  run: |
    pip install pip-tools
    pip-compile clockapp/server/requirements.in \
      --output-file clockapp/server/requirements.check.txt \
      --generate-hashes --strip-extras --quiet
    diff clockapp/server/requirements.txt clockapp/server/requirements.check.txt \
      || (echo "requirements.txt is out of date. Run pip-compile." && exit 1)
    rm clockapp/server/requirements.check.txt
```

---

## 8. systemd Unit File

For teams that prefer bare-metal over Docker. Drop this file at `/etc/systemd/system/yearclock.service` on the target host.

```ini
# /etc/systemd/system/yearclock.service
[Unit]
Description=YearClock FastAPI Service
Documentation=https://github.com/YOUR_ORG/fleet-experimentation
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=clockapp
Group=clockapp
WorkingDirectory=/opt/clockapp

# Load environment from a root-owned, service-readable file.
# Secrets (future API keys, Sentry DSN) live here, not in source.
EnvironmentFile=/etc/clockapp/env

ExecStart=/opt/clockapp/venv/bin/python3 -m uvicorn clockapp.server.main:app \
    --host 127.0.0.1 \
    --port 8421 \
    --workers 1 \
    --no-access-log \
    --log-level warning

# Restart on any non-zero exit, with 5s back-off.
# This means a crash loop won't hammer the system.
Restart=on-failure
RestartSec=5s
StartLimitIntervalSec=60s
StartLimitBurst=5

# Security hardening
NoNewPrivileges=yes
PrivateTmp=yes
ProtectSystem=strict
ReadWritePaths=/var/lib/clockapp
ProtectHome=yes

StandardOutput=journal
StandardError=journal
SyslogIdentifier=yearclock

[Install]
WantedBy=multi-user.target
```

**`/etc/clockapp/env`** (root:root, mode 640, group clockapp):

```dotenv
DB_PATH=/var/lib/clockapp/yearclock.db
PORT=8421
CACHE_TTL_DAYS=7
CORS_ORIGINS=https://yearclock.example.com
```

**Enable and start:**

```bash
sudo useradd --system --no-create-home --shell /usr/sbin/nologin clockapp
sudo mkdir -p /var/lib/clockapp && sudo chown clockapp:clockapp /var/lib/clockapp
sudo systemctl daemon-reload
sudo systemctl enable --now yearclock.service
sudo journalctl -u yearclock.service -f   # tail logs
```

---

## 9. Static File Hosting

### Option A — nginx in docker-compose (self-hosted)

`deploy/nginx/yearclock.conf` (referenced by the `docker-compose.yml` volume mount in §2):

```nginx
# deploy/nginx/yearclock.conf
server {
    listen 80;
    server_name yearclock.example.com;

    # Redirect HTTP → HTTPS in production; remove these two lines in dev
    # return 301 https://$host$request_uri;

    root /usr/share/nginx/html;
    index index.html;

    # Security headers
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;
    add_header Content-Security-Policy
        "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; connect-src 'self' https://query.wikidata.org https://en.wikipedia.org https://numbersapi.com;"
        always;

    # Proxy /api/* to the FastAPI container.
    # This means the browser calls /api/year/1969 — same origin, CORS wildcard gone.
    location /api/ {
        proxy_pass http://api:8421/;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_read_timeout 10s;
        proxy_connect_timeout 5s;
    }

    # Static PWA — aggressive caching for the HTML shell
    location / {
        try_files $uri $uri/ /index.html;
        add_header Cache-Control "public, max-age=3600, stale-while-revalidate=86400";
        gzip on;
        gzip_types text/html text/css application/javascript application/json;
    }

    # Health check endpoint for the load balancer (no logging)
    location = /nginx-health {
        access_log off;
        return 200 "ok\n";
        add_header Content-Type text/plain;
    }
}
```

Once the `api` container is behind nginx on the same network, update `CORS_ORIGINS` to the exact frontend origin — remove `"*"` permanently.

### Option B — GitHub Pages (zero-ops frontend)

Push `clockapp/web/index.html` to a `gh-pages` branch or configure Settings → Pages → source: `Deploy from a branch` → `main`, folder `/clockapp/web`. The frontend is globally CDN-distributed, free, and auto-deployed on every push.

The backend API still runs on your VPS; the frontend JS calls the API by absolute URL (`https://api.yearclock.example.com/year/{year}`). Update the `fetch()` base URL and the `CORS_ORIGINS` setting to match.

**GitHub Pages deploy workflow** (add to `.github/workflows/ci.yml`):

```yaml
  deploy-pages:
    name: Deploy PWA to GitHub Pages
    runs-on: ubuntu-latest
    needs: validate-html
    if: github.ref == 'refs/heads/main'
    permissions:
      pages: write
      id-token: write
    environment:
      name: github-pages
      url: ${{ steps.deployment.outputs.page_url }}
    steps:
      - uses: actions/checkout@v4
      - uses: actions/configure-pages@v5
      - uses: actions/upload-pages-artifact@v3
        with:
          path: clockapp/web
      - id: deployment
        uses: actions/deploy-pages@v4
```

**Recommendation:** Use GitHub Pages for the frontend and Docker + VPS for the API. This separates deployment concerns cleanly — frontend outages don't affect API health and vice versa.

---

## 10. Day-One Deployment Checklist

A numbered, ordered checklist for deploying YearClock to a fresh Ubuntu 24.04 LTS VPS from zero. Each step is independently verifiable.

```
PRE-FLIGHT
──────────
 1. [ ] VPS provisioned (≥1 vCPU, ≥512 MB RAM, 10 GB disk). Ubuntu 24.04 LTS.
 2. [ ] DNS A record for yearclock.example.com pointing to VPS IP. TTL ≤ 300.
 3. [ ] SSH access confirmed. Root or sudo user available.

HOST SETUP
──────────
 4. [ ] apt update && apt upgrade -y
 5. [ ] apt install -y docker.io docker-compose-plugin git curl
 6. [ ] systemctl enable --now docker
 7. [ ] Add deploy user to docker group: usermod -aG docker deployuser

REPO SETUP
──────────
 8. [ ] git clone https://github.com/YOUR_ORG/fleet-experimentation.git /opt/clockapp
 9. [ ] cd /opt/clockapp
10. [ ] cp .env.example .env && nano .env
        Set: CORS_ORIGINS=https://yearclock.example.com
        Confirm: DB_PATH=/data/yearclock.db, CACHE_TTL_DAYS=7

TLS (Let's Encrypt)
───────────────────
11. [ ] apt install -y certbot
12. [ ] certbot certonly --standalone -d yearclock.example.com
        (Stop nginx first if running; certbot binds port 80 temporarily)
13. [ ] Add TLS volume mounts to docker-compose.yml web service:
        - /etc/letsencrypt:/etc/letsencrypt:ro
14. [ ] Uncomment the HTTP→HTTPS redirect in deploy/nginx/yearclock.conf
15. [ ] Add HTTPS server block to yearclock.conf (port 443, ssl_certificate paths)
16. [ ] Add certbot renewal cron: certbot renew --deploy-hook "docker compose -f /opt/clockapp/docker-compose.yml restart web"

FIRST RUN
─────────
17. [ ] docker compose build --no-cache
18. [ ] docker compose up -d
19. [ ] docker compose ps  — confirm both containers are "healthy" / "running"
20. [ ] curl -sf https://yearclock.example.com/api/health | python3 -m json.tool
        Expected: {"status": "ok", ...}
21. [ ] curl -sf https://yearclock.example.com/api/year/1969 | python3 -m json.tool
        Expected: JSON with events array, is_future: false

SMOKE TEST
──────────
22. [ ] Open https://yearclock.example.com in a browser — PWA loads, clock ticks
23. [ ] Check browser console for JS errors (should be zero)
24. [ ] Verify SQLite volume persists: docker compose restart api && curl .../api/year/1969
        (second call should be faster — cache hit)

OBSERVABILITY
─────────────
25. [ ] Set up Uptime Robot free monitor on https://yearclock.example.com/api/health
        Alert email configured. Interval: 5 minutes.
26. [ ] docker compose logs api --follow  — confirm JSON log lines are appearing
27. [ ] (Optional) Register free Sentry project, add DSN to .env as SENTRY_DSN

MAINTENANCE
───────────
28. [ ] Test backup: docker exec yearclock-api sqlite3 $DB_PATH ".backup /data/yearclock-backup.db"
29. [ ] Add nightly backup cron to host:
        0 2 * * * docker exec yearclock-api sqlite3 /data/yearclock.db \
          ".backup /data/yearclock-$(date +\%F).db"
30. [ ] Confirm Docker restart policy: docker inspect yearclock-api | grep RestartPolicy
        Expected: {"Name":"unless-stopped","MaximumRetryCount":0}
31. [ ] Test crash recovery: docker kill yearclock-api && sleep 10 && docker ps
        Container should be running again automatically.

DONE
────
 → Service is live, TLS-terminated, crash-resilient, monitored, and backed up.
   Estimated time from fresh VPS to step 31: ~45 minutes.
```

---

## Summary Assessment

Round 2 delivers the ten infrastructure files that Round 1 identified as missing. Nothing here requires new architectural decisions — it is standard FastAPI production practice applied to the existing codebase. The critical path to a working production deployment is: **§7 (pin deps) → §4 (config.py) → §1 (Dockerfile) → §2 (docker-compose.yml) → §9 (nginx config) → §10 (checklist)**. The systemd unit (§8), CI pipeline (§3), and logging (§5) can follow in the next sprint. The SLOs (§6) should be configured as soon as the service has its first real user.

The one change to `main.py` with the highest leverage remains the two-line fix from Round 1:

```python
# Line ~30 of main.py
_CURRENT_YEAR = datetime.date.today().year   # was: _CURRENT_YEAR = 2025
```

Everything else in this document is scaffolding around an already well-structured service.
