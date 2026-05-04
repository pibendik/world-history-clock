# Build stage
# Build context must be the clockapp/ directory (docker compose -f docker-compose.prod.yml build)
FROM python:3.12-slim AS builder
WORKDIR /build
COPY server/requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# Runtime stage
FROM python:3.12-slim
WORKDIR /app

# Non-root user
RUN useradd -m -u 1000 appuser

# Copy installed packages
COPY --from=builder /install /usr/local

# Copy application code (. = clockapp/ directory, mounted as ./clockapp/ for the module path)
COPY . ./clockapp/

# Data directory (owned by appuser)
RUN mkdir -p /data && chown appuser /data

USER appuser

ENV YEARCLOCK_DB_PATH=/data/yearclock.db

EXPOSE 8421

HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
  CMD python3 -c "import urllib.request; urllib.request.urlopen('http://localhost:8421/health')" || exit 1

CMD ["python3", "-m", "uvicorn", "clockapp.server.main:app", "--host", "0.0.0.0", "--port", "8421", "--workers", "1"]
