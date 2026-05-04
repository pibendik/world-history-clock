#!/usr/bin/env bash
# deploy.sh — deploy YearClock to your production server in one command
#
# Usage:
#   ./deploy.sh root@5.75.123.45
#
# What this does:
#   1. Copies your local .env to the server (first deploy only)
#   2. SSHes in, pulls latest code, rebuilds and restarts containers
#   3. Runs a health check and prints the result
#
# Prerequisites on your LOCAL machine:
#   - SSH access configured: ssh-keygen + ssh-copy-id root@YOUR_SERVER_IP
#   - Latest code pushed to GitHub/GitLab
#   - .env file with YEARCLOCK_DOMAIN set
#
# Prerequisites on the SERVER (see SERVER-SETUP.md — do this once):
#   - Docker + docker compose installed
#   - This repo cloned to /opt/yearclock

set -euo pipefail

SERVER="${1:-}"
if [[ -z "$SERVER" ]]; then
    echo "Usage: $0 user@server-ip"
    echo "Example: $0 root@5.75.123.45"
    exit 1
fi

REPO_DIR="${DEPLOY_DIR:-/opt/yearclock}"

echo "▶ Deploying YearClock to $SERVER:$REPO_DIR"
echo ""

# --- 1. Copy .env if not present on server ---
echo "📋 Syncing .env..."
if ssh "$SERVER" "test -f $REPO_DIR/.env" 2>/dev/null; then
    echo "   .env already present on server — not overwritten"
    echo "   (edit it manually on the server if you need to change settings)"
else
    scp .env "$SERVER:$REPO_DIR/.env"
    echo "   .env uploaded"
fi

# --- 2. Pull latest code ---
echo ""
echo "⬇  Pulling latest code on server..."
ssh "$SERVER" bash <<EOF
set -e
cd $REPO_DIR
git pull --ff-only
echo "   \$(git log -1 --pretty='%h %s')"
EOF

# --- 3. Build and restart containers ---
echo ""
echo "🔨 Building and restarting containers..."
ssh "$SERVER" bash <<EOF
set -e
cd $REPO_DIR
docker compose -f docker-compose.prod.yml up -d --build --remove-orphans
EOF

# --- 4. Health check ---
echo ""
echo "🩺 Waiting for health check (15s)..."
sleep 15

DOMAIN=$(grep ^YEARCLOCK_DOMAIN .env | cut -d= -f2 | tr -d '"')
HTTP_STATUS=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 "https://$DOMAIN/api/v1/year/2000" || echo "000")

if [[ "$HTTP_STATUS" == "200" ]]; then
    echo ""
    echo "✅ Deploy successful! App is live at https://$DOMAIN"
else
    echo ""
    echo "⚠️  Health check returned HTTP $HTTP_STATUS (expected 200)"
    echo "   Check logs:"
    echo "   ssh $SERVER 'cd $REPO_DIR && docker compose -f docker-compose.prod.yml logs --tail=50'"
fi
