# clockapp — Kubernetes Deployment Plan (NILU Platform / ArgoCD)

> Target platform: NILU Kubernetes (dkub → pkub)  
> GitOps tool: ArgoCD  
> Manifest layout: Kustomize base + overlays  
> Last updated: see git log

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [Pre-Deployment Checklist](#2-pre-deployment-checklist)
3. [Repository Structure](#3-repository-structure)
4. [Kustomize Layout](#4-kustomize-layout)
5. [Image Tagging Strategy](#5-image-tagging-strategy)
6. [Storage Decision](#6-storage-decision)
7. [CI/CD Pipeline Sketch](#7-cicd-pipeline-sketch)
8. [Helpdesk Tickets Needed](#8-helpdesk-tickets-needed)
9. [Open Questions Before Finalising Manifests](#9-open-questions-before-finalising-manifests)

---

## 1. Architecture Overview

### Request Flow

```
                        NILU Network / Internet
                               │
                    ┌──────────▼──────────┐
                    │       HAProxy        │  (IT-managed reverse proxy)
                    │  dev-yearclock.nilu.no (dkub)
                    │  yearclock.nilu.no   (pkub)
                    └──────────┬──────────┘
                               │ HTTPS
                    ┌──────────▼──────────┐
                    │  Traefik Ingress     │  (IngressRoute + cert-manager TLS)
                    │  yearclock.dkub.nilu.no  /  yearclock.pkub.nilu.no
                    └──────────┬──────────┘
                               │
              Namespace: fleet-yearclock
              ┌────────────────▼────────────────────┐
              │                                     │
   ┌──────────▼──────────┐             ┌────────────▼────────────┐
   │  fleet-yearclock-   │   /api/ →   │  fleet-yearclock-       │
   │  web-deploy         │ ──────────► │  api-deploy             │
   │  (nginx, port 80)   │             │  (FastAPI, port 8421)   │
   │  Serves PWA static  │             │                         │
   │  assets             │             │  ┌──────────────────┐   │
   └─────────────────────┘             │  │  Longhorn PVC    │   │
                                       │  │  1Gi RWO         │   │
                                       │  │  /data/          │   │
                                       │  │  yearclock.db    │   │
                                       │  └──────────────────┘   │
                                       └─────────────────────────┘
```

### Component Summary

| Component | Image | Port | Purpose |
|---|---|---|---|
| `fleet-yearclock-web-deploy` | `<registry>/yearclock-web` | 80 | nginx serving PWA; proxies `/api/*` to api service |
| `fleet-yearclock-api-deploy` | `<registry>/yearclock-api` | 8421 | FastAPI backend; reads/writes SQLite at `/data/yearclock.db` |
| `fleet-yearclock-api-pvc` | — | — | Longhorn 1Gi RWO volume for the SQLite database file |

---

## 2. Pre-Deployment Checklist

Work through these steps in order. Items marked **[IT]** require a helpdesk ticket; items marked **[You]** are your own actions.

### Phase 1 — Platform Access

- [ ] **[IT]** Confirm or request ArgoCD project `fleet` at https://argocd.dkub.nilu.no  
  _(skip if the project already exists — verify with IT or in the ArgoCD UI)_
- [ ] **[IT]** Request namespace `fleet-yearclock` under the `fleet` project  
  _(ticket details in [Section 8](#8-helpdesk-tickets-needed))_
- [ ] **[You]** Verify you are a member of the Keycloak group that has project-admin rights for `fleet`

### Phase 2 — Container Images

- [ ] **[You]** Decide on image registry (see [Section 9](#9-open-questions-before-finalising-manifests))  
  Recommended: `ghcr.io/<github-username>/yearclock-api` and `ghcr.io/<github-username>/yearclock-web`
- [ ] **[You]** Create a `Dockerfile` for the web service (nginx serving `clockapp/web/`)  
  _(the API already has `clockapp/server/Dockerfile`)_
- [ ] **[You]** Build and push the API image:
  ```bash
  docker build -f clockapp/server/Dockerfile -t ghcr.io/<username>/yearclock-api:v0.1.0 .
  docker push ghcr.io/<username>/yearclock-api:v0.1.0
  ```
- [ ] **[You]** Build and push the web image:
  ```bash
  docker build -f clockapp/web/Dockerfile -t ghcr.io/<username>/yearclock-web:v0.1.0 .
  docker push ghcr.io/<username>/yearclock-web:v0.1.0
  ```
- [ ] **[You]** If using a private registry, create an `imagePullSecret` in the namespace and reference it in the Deployment specs

### Phase 3 — Kubernetes Manifests

- [ ] **[You]** Fill in actual image references and tags in `clockapp/k8s/base/`
- [ ] **[You]** Fill in dkub overlay ingress hostname: `yearclock.dkub.nilu.no`
- [ ] **[You]** Fill in pkub overlay ingress hostname: `yearclock.pkub.nilu.no`
- [ ] **[You]** Run `kubectl kustomize clockapp/k8s/overlays/dkub` locally and review the output before pushing

### Phase 4 — ArgoCD Application (dkub)

- [ ] **[You]** Create an ArgoCD Application named `fleet-yearclock` on https://argocd.dkub.nilu.no  
  pointing to `clockapp/k8s/overlays/dkub` in this repository
- [ ] **[You]** Sync the application and verify pods become `Running` in namespace `fleet-yearclock`
- [ ] **[You]** Check the web UI at `https://yearclock.dkub.nilu.no` (internal cluster URL)

### Phase 5 — External Access (dkub)

- [ ] **[IT]** Submit helpdesk ticket requesting HAProxy route `dev-yearclock.nilu.no` → dkub ingress  
  _(ticket details in [Section 8](#8-helpdesk-tickets-needed))_
- [ ] **[You]** Verify external access at `https://dev-yearclock.nilu.no`

### Phase 6 — Promotion to pkub

- [ ] **[You]** Pin a release image tag for production (e.g. `v0.1.0`)
- [ ] **[You]** Create an ArgoCD Application named `fleet-yearclock` on https://argocd.pkub.nilu.no  
  pointing to `clockapp/k8s/overlays/pkub`
- [ ] **[IT]** Submit helpdesk ticket requesting HAProxy route `yearclock.nilu.no` → pkub ingress
- [ ] **[You]** Verify at `https://yearclock.nilu.no`

---

## 3. Repository Structure

### Single-Repo Approach (Recommended for This Project)

For a personal/small project at this scale, keeping application source code and Kubernetes manifests in the **same repository** is the simplest approach. There is no hard requirement from the NILU platform to use two separate repos.

```
fleet-experimentation/               ← application + manifests repo
├── clockapp/
│   ├── server/                      ← FastAPI source + Dockerfile
│   │   └── Dockerfile
│   ├── web/                         ← Static PWA (index.html, assets)
│   │   └── Dockerfile               ← nginx image serving the PWA
│   └── k8s/                         ← Kubernetes manifests (this folder)
│       ├── DEPLOYMENT-PLAN.md       ← this document
│       ├── base/                    ← shared manifests (cluster-agnostic)
│       └── overlays/
│           ├── dkub/                ← dkub-specific patches (hostname, tag)
│           └── pkub/                ← pkub-specific patches (hostname, tag)
└── ...
```

**ArgoCD watches `clockapp/k8s/overlays/<cluster>`** in this repo. When you push a manifest change (e.g. a new image tag), ArgoCD detects it and syncs the cluster.

> **Two-repo alternative:** Separating the manifest repo is recommended when multiple teams share the same platform and you want strict RBAC over who can push manifest changes. Not needed here.

---

## 4. Kustomize Layout

```
clockapp/k8s/
├── base/
│   ├── kustomization.yaml          # lists all base resources
│   ├── deployment-api.yaml         # fleet-yearclock-api-deploy
│   ├── deployment-web.yaml         # fleet-yearclock-web-deploy
│   ├── service-api.yaml            # fleet-yearclock-api-svc  (port 8421)
│   ├── service-web.yaml            # fleet-yearclock-web-svc  (port 80)
│   └── pvc.yaml                    # fleet-yearclock-api-pvc  (Longhorn 1Gi)
└── overlays/
    ├── dkub/
    │   ├── kustomization.yaml      # bases: ../../base; patches below
    │   ├── ingress.yaml            # IngressRoute + Certificate for dkub
    │   └── image-tag-patch.yaml    # (optional) set :dev rolling tag
    └── pkub/
        ├── kustomization.yaml      # bases: ../../base; patches below
        ├── ingress.yaml            # IngressRoute + Certificate for pkub
        └── image-tag-patch.yaml    # pin to e.g. :v0.1.0
```

### Resource Naming Reference

Following NILU convention `<project>-<namespace>-<type>`:

| Resource | Name |
|---|---|
| Namespace | `fleet-yearclock` |
| API Deployment | `fleet-yearclock-api-deploy` |
| Web Deployment | `fleet-yearclock-web-deploy` |
| API Service | `fleet-yearclock-api-svc` |
| Web Service | `fleet-yearclock-web-svc` |
| PVC | `fleet-yearclock-api-pvc` |
| IngressRoute | `fleet-yearclock-ing` |
| Certificate | `fleet-yearclock-cert` |
| TLS Secret | `fleet-yearclock-cert-secret` |
| ArgoCD Application | `fleet-yearclock` |

### Example: `base/kustomization.yaml`

```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
namespace: fleet-yearclock
resources:
  - deployment-api.yaml
  - deployment-web.yaml
  - service-api.yaml
  - service-web.yaml
  - pvc.yaml
```

### Example: `overlays/dkub/kustomization.yaml`

```yaml
apiVersion: kustomize.config.k8s.io/v1beta1
kind: Kustomization
namespace: fleet-yearclock
bases:
  - ../../base
resources:
  - ingress.yaml
images:
  - name: yearclock-api
    newName: ghcr.io/<username>/yearclock-api
    newTag: dev
  - name: yearclock-web
    newName: ghcr.io/<username>/yearclock-web
    newTag: dev
```

### Example: `overlays/dkub/ingress.yaml`

```yaml
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: fleet-yearclock-cert
  namespace: fleet-yearclock
spec:
  secretName: fleet-yearclock-cert-secret
  issuerRef:
    name: cert-manager-clusterissuer
    kind: ClusterIssuer
  dnsNames:
    - yearclock.dkub.nilu.no
---
apiVersion: traefik.io/v1alpha1
kind: IngressRoute
metadata:
  name: fleet-yearclock-ing
  namespace: fleet-yearclock
spec:
  entryPoints:
    - websecure
  routes:
    - kind: Rule
      match: Host(`yearclock.dkub.nilu.no`)
      services:
        - name: fleet-yearclock-web-svc
          port: 80
  tls:
    secretName: fleet-yearclock-cert-secret
```

---

## 5. Image Tagging Strategy

### Development (dkub)

| Approach | Tag | Notes |
|---|---|---|
| Rolling build | `:dev` | CI pushes on every merge to `main`; ArgoCD must have `imagePullPolicy: Always` + short reconcile interval, **or** the tag must change (e.g. `:main-abc1234`) |
| Build SHA tag | `:main-<sha7>` | Better: each commit produces a unique tag; ArgoCD sees a manifest change and auto-syncs without extra config |

**Recommendation for dkub:** use a short-SHA tag (`ghcr.io/<user>/yearclock-api:main-abc1234`). CI updates the Kustomize `newTag` field and commits back to the repo. ArgoCD detects the change and syncs automatically.

### Production (pkub)

- Always use a pinned **semantic version** tag: `v0.1.0`, `v1.2.3`, etc.
- Update the tag in `overlays/pkub/kustomization.yaml` manually (or via a release CI step) and commit.
- Never use `:latest` in production — ArgoCD cannot detect image changes without a manifest diff.

---

## 6. Storage Decision

### Use Longhorn for the SQLite PVC

The API writes a SQLite database file at `/data/yearclock.db`. This must survive:
- Pod restarts (e.g. after a config change or crash)
- Monthly cluster maintenance (nodes are patched and restarted)
- Pod reschedule to a different node (e.g. node drain)

**`longhorn` is the correct storage class.** It provides 3-way replication across cluster nodes so the volume is available regardless of which node the pod lands on.

```yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: fleet-yearclock-api-pvc
  namespace: fleet-yearclock
spec:
  accessModes:
    - ReadWriteOnce
  storageClassName: longhorn
  resources:
    requests:
      storage: 1Gi
```

### Why NOT `local-path`

`local-path` stores data on the disk of the specific node the pod runs on. If the pod is rescheduled to a different node (routine during maintenance, node failures, or scaling), **the database file is gone**. For a SQLite database this means permanent data loss with no recovery path.

| Storage Class | Survives node reschedule? | Backup support? | Right for SQLite DB? |
|---|---|---|---|
| `longhorn` | ✅ Yes (3-way replication) | ✅ Snapshots | ✅ **Use this** |
| `local-path` | ❌ No — data lost | ❌ None | ❌ Do not use |

> **Note on size:** 1Gi is generous for a SQLite clock app. SQLite files are typically a few MB unless you store large blobs. Start with 1Gi; you can resize later.

---

## 7. CI/CD Pipeline Sketch

### GitHub Actions → Build → Push → Update Manifest → ArgoCD Sync

```
┌─────────────────────────────────────────────────────────┐
│                   GitHub Actions                        │
│                                                         │
│  Trigger: push to main (or tag v*)                      │
│                                                         │
│  1. Build API image                                     │
│     docker build -f clockapp/server/Dockerfile          │
│     Tag: ghcr.io/<user>/yearclock-api:main-${{ sha }}   │
│                                                         │
│  2. Build web image                                     │
│     docker build -f clockapp/web/Dockerfile             │
│     Tag: ghcr.io/<user>/yearclock-web:main-${{ sha }}   │
│                                                         │
│  3. Push both images to ghcr.io                         │
│                                                         │
│  4. Update manifest (dkub overlay)                      │
│     cd clockapp/k8s/overlays/dkub                       │
│     kustomize edit set image \                          │
│       yearclock-api=ghcr.io/<user>/yearclock-api:main-$SHA │
│       yearclock-web=ghcr.io/<user>/yearclock-web:main-$SHA │
│     git commit -am "ci: update image tags to $SHA"      │
│     git push                                            │
│                                                         │
│  5. ArgoCD detects manifest change → auto-syncs dkub   │
└─────────────────────────────────────────────────────────┘
```

### Production Promotion (Manual)

```
┌─────────────────────────────────────────────────────────┐
│  Trigger: create git tag e.g. v0.2.0                    │
│                                                         │
│  1. Build + push with tag :v0.2.0                       │
│  2. Update clockapp/k8s/overlays/pkub/kustomization.yaml│
│     with newTag: v0.2.0                                 │
│  3. git push → ArgoCD (pkub) auto-syncs                 │
└─────────────────────────────────────────────────────────┘
```

### Minimal `.github/workflows/ci.yaml` Outline

```yaml
name: Build and Deploy

on:
  push:
    branches: [main]
  release:
    types: [published]

jobs:
  build-push-update:
    runs-on: ubuntu-latest
    permissions:
      contents: write
      packages: write
    steps:
      - uses: actions/checkout@v4

      - name: Log in to GHCR
        uses: docker/login-action@v3
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}

      - name: Set image tag
        run: echo "TAG=main-$(git rev-parse --short HEAD)" >> $GITHUB_ENV

      - name: Build and push API
        uses: docker/build-push-action@v5
        with:
          context: .
          file: clockapp/server/Dockerfile
          push: true
          tags: ghcr.io/${{ github.repository_owner }}/yearclock-api:${{ env.TAG }}

      - name: Build and push web
        uses: docker/build-push-action@v5
        with:
          context: clockapp/web
          file: clockapp/web/Dockerfile
          push: true
          tags: ghcr.io/${{ github.repository_owner }}/yearclock-web:${{ env.TAG }}

      - name: Update dkub manifest
        run: |
          cd clockapp/k8s/overlays/dkub
          kustomize edit set image \
            yearclock-api=ghcr.io/${{ github.repository_owner }}/yearclock-api:${{ env.TAG }} \
            yearclock-web=ghcr.io/${{ github.repository_owner }}/yearclock-web:${{ env.TAG }}
          git config user.name "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"
          git commit -am "ci: bump dkub images to ${{ env.TAG }}" || echo "No changes"
          git push
```

---

## 8. Helpdesk Tickets Needed

Submit these tickets to IT via the NILU helpdesk system. Include the exact information listed below.

---

### Ticket 1 — Request ArgoCD Project (if not already exists)

**Subject:** Request ArgoCD project `fleet` on dkub and pkub

**Body:**
> Please create an ArgoCD project named `fleet` on both:
> - https://argocd.dkub.nilu.no
> - https://argocd.pkub.nilu.no
>
> Please add my user `<your-username>` as a project admin via the Keycloak group for this project.
>
> Repository to allow: `https://github.com/<owner>/fleet-experimentation`

---

### Ticket 2 — Request Namespace `fleet-yearclock`

**Subject:** Request namespace `fleet-yearclock` in ArgoCD project `fleet`

**Body:**
> Please create namespace `fleet-yearclock` under the `fleet` project on dkub (and later on pkub).
>
> This namespace will host the `yearclock` clock application (FastAPI + nginx PWA).

---

### Ticket 3 — External Access on dkub (dev)

**Subject:** HAProxy route for dev-yearclock.nilu.no → dkub

**Body:**
> Please configure HAProxy to route inbound traffic for `dev-yearclock.nilu.no` to:
>
> - **Cluster:** dkub
> - **Internal ingress hostname:** `yearclock.dkub.nilu.no`
> - **Protocol:** HTTPS
>
> The Traefik IngressRoute and TLS certificate will be managed by the app team.

---

### Ticket 4 — External Access on pkub (production)

**Subject:** HAProxy route for yearclock.nilu.no → pkub

**Body:**
> Please configure HAProxy to route inbound traffic for `yearclock.nilu.no` to:
>
> - **Cluster:** pkub
> - **Internal ingress hostname:** `yearclock.pkub.nilu.no`
> - **Protocol:** HTTPS
>
> The Traefik IngressRoute and TLS certificate will be managed by the app team.

---

## 9. Open Questions Before Finalising Manifests

Answer these before writing the actual YAML files. Defaults/recommendations are noted.

---

### Q1 — Image Registry

**Question:** Where will the container images be hosted?

| Option | When to use |
|---|---|
| `ghcr.io/<github-username>/` | ✅ Recommended if this repo is on GitHub — free for public repos, integrates with `GITHUB_TOKEN` for auth |
| NILU Harbor (future) | When available on the NILU platform (see `FUTURE.md`) |
| Docker Hub | Works, but rate-limited; requires separate credentials secret |

**Action required:** Replace every `<registry>` and `<username>` placeholder in the manifests with your actual registry path.

---

### Q2 — Pod Architecture: Separate Pods or Sidecar?

**Question:** Should the nginx web server and the FastAPI API run as separate Deployments, or as two containers in the same pod (sidecar pattern)?

| Option | Pros | Cons |
|---|---|---|
| **Two separate Deployments** (recommended) | Independent scaling; independent restart; cleaner ArgoCD view; each can be updated without touching the other | Two Services; slightly more YAML |
| **Single pod, two containers (sidecar)** | nginx and API share localhost — no inter-service DNS needed; single unit | Cannot scale independently; if one crashes both restart; harder to update one image at a time |

**Recommendation:** Use **two separate Deployments**. At this scale both run as `replicas: 1`, but separation is operationally cleaner and follows platform patterns.

---

### Q3 — Does the `fleet` ArgoCD Project Already Exist?

**Question:** Is there already a project named `fleet` in ArgoCD on dkub/pkub?

- **Yes →** Skip Ticket 1; proceed with Ticket 2 (namespace request).
- **No →** Submit Ticket 1 first, then Ticket 2.

Check at https://argocd.dkub.nilu.no → Settings → Projects.

---

### Q4 — nginx Dockerfile for the Web Service

**Question:** Does `clockapp/web/Dockerfile` exist yet?

The web static files live at `clockapp/web/index.html` and associated assets. An nginx container needs to:
1. Copy the static files into `/usr/share/nginx/html/`
2. Configure `/api/` proxy_pass to `http://fleet-yearclock-api-svc:8421/`

If this Dockerfile does not exist yet, it must be created before images can be built and pushed.

---

*End of deployment plan.*
