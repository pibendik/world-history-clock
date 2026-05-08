#!/usr/bin/env bash
# deploy.sh — deploy YearClock to your production server in one command
#
# Usage (from your LOCAL machine, after git push):
#   ./deploy.sh root@YOUR_SERVER_IP
#
# Flags:
#   --clear-cache    Wipe the SQLite event cache BEFORE the new container
#                    starts (against the OLD running container) so the cache
#                    warmer finds an empty cache and processes all years with
#                    LLM scoring active.  Use after changing content filters
#                    so old garbage is refetched.
#
# What this does:
#   1. SSHes in, pulls latest code
#   2. Optionally clears the event cache on the OLD (still-running) container
#   3. Rebuilds and restarts the API container (new code + dependencies)
#   4. Restarts Caddy (picks up any web file changes)
#   5. Runs a health check and prints the result
#
# Prerequisites on your LOCAL machine:
#   - SSH access: ssh-keygen + ssh-copy-id root@YOUR_SERVER_IP
#   - Latest code already pushed to GitHub (git push first!)
#
# Prerequisites on the SERVER (see SERVER-SETUP.md — one-time setup):
#   - Docker + docker compose installed
#   - Repo cloned to /opt/historieklokka
#   - .env file with YEARCLOCK_DOMAIN set

set -euo pipefail

SERVER="${1:-}"
CLEAR_CACHE=false

# Parse flags
for arg in "$@"; do
    case $arg in
        --clear-cache) CLEAR_CACHE=true ;;
    esac
done

if [[ -z "$SERVER" ]] || [[ "$SERVER" == --* ]]; then
    echo "Usage: $0 user@server-ip [--clear-cache]"
    echo "Example: $0 root@5.75.123.45"
    echo "Example: $0 root@5.75.123.45 --clear-cache"
    exit 1
fi

REPO_DIR="${DEPLOY_DIR:-/opt/historieklokka}"

echo "▶ Deploying YearClock to $SERVER:$REPO_DIR"
echo ""

# Read domain from server early — needed for the pre-build cache clear.
# (Not stored locally because .env is gitignored.)
DOMAIN=$(ssh "$SERVER" "grep ^YEARCLOCK_DOMAIN $REPO_DIR/.env 2>/dev/null | cut -d= -f2 | tr -d '\"'" 2>/dev/null || echo "")

# --- 1. Pull latest code ---
echo "⬇  Pulling latest code..."
ssh "$SERVER" bash <<EOF
set -e
cd $REPO_DIR
git pull --ff-only
echo "   \$(git log -1 --pretty='%h %s')"
EOF

# --- 2. Optionally clear event cache on the OLD (still-running) container ---
#
# This MUST happen before "docker compose up --build" because the cache warmer
# starts immediately after the new container is up and skips already-cached
# years without sleeping — finishing in <10s.  If we cleared the cache after
# the restart the warmer would already be done and the cache would stay empty
# until 04:00 UTC next day.  Clearing against the old container guarantees the
# new container's warmer finds an empty cache and runs LLM scoring for all
# 1440 years.
#
# If the old container isn't running (first deploy) the curl call will fail
# gracefully — we catch the error and continue.
if [[ "$CLEAR_CACHE" == true ]]; then
    echo ""
    echo "🗑  Clearing event cache on OLD container (before restart)..."
    if [[ -n "$DOMAIN" ]]; then
        curl -s -o /dev/null -w "   DELETE /api/v1/cache → HTTP %{http_code}\n" \
            --max-time 15 -X DELETE "https://$DOMAIN/api/v1/cache" || \
            echo "   ⚠️  Cache-clear request failed (old container not running?) — continuing"
    else
        echo "   ⚠️  YEARCLOCK_DOMAIN not set — skipping HTTP cache clear"
    fi
fi

# --- 3. Rebuild API (picks up Python/server changes) ---
echo ""
echo "🔨 Rebuilding API container..."
ssh "$SERVER" bash <<EOF
set -e
cd $REPO_DIR
docker compose -f docker-compose.prod.yml up -d --build --remove-orphans api
EOF

# --- 4. Restart Caddy (picks up web/ static file changes) ---
echo ""
echo "🔄 Restarting Caddy (web files)..."
ssh "$SERVER" bash <<EOF
set -e
cd $REPO_DIR
docker compose -f docker-compose.prod.yml restart caddy
EOF

# --- 5. Health check ---
echo ""
echo "🩺 Waiting for health check (20s)..."
sleep 20

# DOMAIN was already read before the build step (above).

if [[ -z "$DOMAIN" ]]; then
    echo "⚠️  Could not read YEARCLOCK_DOMAIN from server .env — using docker exec fallback"
    # Fall back: exec inside the container (port 8421 is expose-only, not reachable from host)
    INTERNAL_OK=$(ssh "$SERVER" "docker exec historieklokka-api-1 python3 -c \"import urllib.request; urllib.request.urlopen('http://localhost:8421/health'); print('200')\" 2>/dev/null" || echo "000")
    if [[ "$INTERNAL_OK" == "200" ]]; then
        echo "✅ API is healthy (internal check passed). Visit your site to confirm."
    else
        echo "⚠️  API health check failed — check logs:"
        echo "   ssh $SERVER 'cd $REPO_DIR && docker compose -f docker-compose.prod.yml logs --tail=50'"
    fi
else
    # Check the PWA landing page (static file — always fast, no Wikidata/cache dependency).
    # Year endpoints can take 30s after --clear-cache so they're unsuitable for a 10s timeout.
    # || true: curl exits non-zero on TLS/network errors; set -euo pipefail would kill the script.
    HTTP_STATUS=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 "https://$DOMAIN/" || true)
    if [[ "$HTTP_STATUS" == "200" ]]; then
        echo ""
        echo "✅ Deploy successful! App is live at https://$DOMAIN"
        if [[ "$CLEAR_CACHE" == true ]]; then
            echo "   Cache cleared — warmer is refilling from current hour forward (~2h for full warm)"
        fi
    else
        echo ""
        echo "⚠️  Health check returned HTTP ${HTTP_STATUS:-000} (expected 200)"
        echo "   Check logs:"
        echo "   ssh $SERVER 'cd $REPO_DIR && docker compose -f docker-compose.prod.yml logs --tail=50'"
    fi
fi
