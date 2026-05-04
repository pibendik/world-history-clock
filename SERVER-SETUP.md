# Publishing YearClock Online — Step-by-Step Guide

A complete walkthrough: from a blank server to a live HTTPS website.
**Total time: ~2 hours. Total monthly cost: ~€5.**

---

## What you'll end up with

- `https://yourdomain.com` — the YearClock PWA (installable on phone too)
- Automatic HTTPS (free certificate via Let's Encrypt, auto-renewed by Caddy)
- FastAPI backend + SQLite cache running behind the scenes
- Everything auto-restarts on server reboot

---

## The moving parts

```
Browser → yourdomain.com → DNS → Hetzner server
                                       ↓ port 443
                                    Caddy (HTTPS)
                                    ↙          ↘
                           /api/*           everything else
                        FastAPI             static PWA files
                        port 8421          (web/index.html)
```

---

## Step 1 — Buy a domain (10 min)

Go to **[porkbun.com](https://porkbun.com)** and search for a name you like.

Suggestions: `yearclock.app` (~$14/yr), `year-clock.com` (~$10/yr)

Buy it. You'll land in a DNS control panel — leave it open, you'll need it in Step 3.

---

## Step 2 — Buy a server (10 min)

Go to **[hetzner.com/cloud](https://www.hetzner.com/cloud)** → "Cloud" → "Add Server".

Settings:
| Field | Value |
|-------|-------|
| Image | **Ubuntu 24.04** |
| Type | **CX22** (2 vCPU, 4 GB RAM) — €4.15/month |
| Datacenter | Helsinki or Frankfurt |
| SSH keys | Paste your public key (`cat ~/.ssh/id_rsa.pub`) |
| Name | `yearclock` |

Click **Create & Buy Now**. Note the server's **public IPv4 address** (e.g. `5.75.123.45`).

> No SSH key yet? Run `ssh-keygen` on your machine, then paste the output of `cat ~/.ssh/id_rsa.pub`.

---

## Step 3 — Point your domain at the server (5 min + wait)

Back in Porkbun, open **DNS** for your domain. Add two records:

| Type | Host | Answer |
|------|------|--------|
| A | `@` | `5.75.123.45` |
| A | `www` | `5.75.123.45` |

`@` means the root (`yourdomain.com`). TTL 600 is fine.

DNS takes 5–60 minutes to propagate. You can continue with setup while it spreads.

---

## Step 4 — Set up the server (one-time, ~20 min)

SSH in:
```bash
ssh root@5.75.123.45
```

### Install Docker
```bash
apt update && apt upgrade -y
curl -fsSL https://get.docker.com | sh
docker --version        # should print Docker version
docker compose version  # should print v2.x
```

### Open the firewall
```bash
ufw allow OpenSSH
ufw allow 80/tcp
ufw allow 443/tcp
ufw enable
```

### Clone the repo
```bash
git clone https://github.com/YOUR_USERNAME/YOUR_REPO.git /opt/yearclock
```

> Replace `YOUR_USERNAME/YOUR_REPO` with your actual GitHub path.
> If the repo is private, set up a [GitHub deploy key](https://docs.github.com/en/authentication/connecting-to-github-with-ssh/managing-deploy-keys).

---

## Step 5 — Configure (5 min)

On the **server**:
```bash
cd /opt/yearclock
cp .env.example .env
nano .env
```

Set your domain:
```env
YEARCLOCK_DOMAIN=yourdomain.com
YEARCLOCK_CORS_ORIGINS=["https://yourdomain.com"]
```

Save with `Ctrl+X` → `Y` → `Enter`.

---

## Step 6 — Launch! (5 min)

Still on the server:
```bash
cd /opt/yearclock
docker compose -f docker-compose.prod.yml up -d --build
```

First run takes ~2 minutes to build. Watch the logs:
```bash
docker compose -f docker-compose.prod.yml logs -f
```

Caddy will print something like:
```
{"level":"info","msg":"certificate obtained successfully","domain":"yourdomain.com"}
```

Then open **`https://yourdomain.com`** in your browser. 🎉

---

## Step 7 — Future deploys (30 seconds each)

On your **local machine**, after pushing changes to git:
```bash
./deploy.sh root@5.75.123.45
```

Script: pulls latest code → rebuilds → restarts → health check.

---

## Useful commands

```bash
# Check what's running
docker ps

# Live logs
docker compose -f docker-compose.prod.yml logs -f

# API health
curl https://yourdomain.com/health

# Cache warm status (how many of 1440 years are cached)
curl https://yourdomain.com/api/v1/cache/status

# Restart everything
docker compose -f docker-compose.prod.yml restart

# Stop everything
docker compose -f docker-compose.prod.yml down
```

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| "Site can't be reached" | Wait for DNS; run `ping yourdomain.com` to check |
| Certificate not issued | DNS must resolve before Caddy can get a cert |
| API 500 errors | Check `docker compose logs api` |
| Empty facts on first load | Cache warmer is running; wait a minute or refresh |

---

## Costs

| Item | Cost |
|------|------|
| Hetzner CX22 | €4.15/month |
| Domain (Porkbun) | ~€10/year |
| TLS cert | **Free** |
| **Total** | **~€5/month** |

To stop paying: delete the Hetzner server in their UI (takes 30 seconds).
