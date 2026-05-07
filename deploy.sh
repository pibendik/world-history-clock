#!/usr/bin/env bash
# deploy.sh — deploy YearClock to your production server in one command
#
# Usage (from your LOCAL machine, after git push):
#   ./deploy.sh root@YOUR_SERVER_IP
#
# Flags:
#   --clear-cache    Wipe the SQLite event cache after deploy (use after
#                    changing content filters so old garbage is refetched)
#
# What this does:
#   1. SSHes in, pulls latest code
#   2. Rebuilds and restarts the API container (new code + dependencies)
#   3. Restarts Caddy (picks up any web file changes)
#   4. Optionally clears the event cache
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

# --- 1. Pull latest code ---
echo "⬇  Pulling latest code..."
ssh "$SERVER" bash <<EOF
set -e
cd $REPO_DIR
git pull --ff-only
echo "   \$(git log -1 --pretty='%h %s')"
EOF

# --- 2. Rebuild API (picks up Python/server changes) ---
echo ""
echo "🔨 Rebuilding API container..."
ssh "$SERVER" bash <<EOF
set -e
cd $REPO_DIR
docker compose -f docker-compose.prod.yml up -d --build --remove-orphans api
EOF

# --- 3. Restart Caddy (picks up web/ static file changes) ---
echo ""
echo "🔄 Restarting Caddy (web files)..."
ssh "$SERVER" bash <<EOF
set -e
cd $REPO_DIR
docker compose -f docker-compose.prod.yml restart caddy
EOF

# --- 4. Optionally clear event cache ---
if [[ "$CLEAR_CACHE" == true ]]; then
    echo ""
    echo "🗑  Clearing event cache (warmer will refill from current time forward)..."
    sleep 5  # give API time to start
    ssh "$SERVER" "docker exec historieklokka-api-1 python3 -c \
        \"import sqlite3; db=sqlite3.connect('/data/yearclock.db'); \
        db.execute('DELETE FROM event_cache'); db.commit(); \
        print('Cache cleared')\""
fi

# --- 5. Health check ---
echo ""
echo "🩺 Waiting for health check (20s)..."
sleep 20

DOMAIN=$(grep ^YEARCLOCK_DOMAIN .env | cut -d= -f2 | tr -d '"')
HTTP_STATUS=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 "https://$DOMAIN/api/v1/year/2000" || echo "000")

if [[ "$HTTP_STATUS" == "200" ]]; then
    echo ""
    echo "✅ Deploy successful! App is live at https://$DOMAIN"
    if [[ "$CLEAR_CACHE" == true ]]; then
        echo "   Cache cleared — warmer is refilling from current hour forward (~2h for full warm)"
    fi
else
    echo ""
    echo "⚠️  Health check returned HTTP $HTTP_STATUS (expected 200)"
    echo "   Check logs:"
    echo "   ssh $SERVER 'cd $REPO_DIR && docker compose -f docker-compose.prod.yml logs --tail=50'"
fi
