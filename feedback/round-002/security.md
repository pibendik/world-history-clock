# Year Clock — Security Review (Round 002)

**Scope:** Concrete mitigations for all findings raised in Round 001  
**Reviewer role:** Application Security Champion  
**Date:** 2025-07-01  
**References:** `clockapp/server/main.py`, `clockapp/web/index.html`, Round 001 `security.md`

---

## 1. Fix the `window` Parameter Bomb

**Round 001 finding:** `GET /year/{year}/buffer?window=10000` triggers up to 40,002 outbound Wikidata HTTP requests in a single unauthenticated call. No upper bound exists on either `window` or `year`.

### Before (vulnerable)

```python
@app.get("/year/{year}")
def get_year(year: int):
    return _build_year_data(year)

@app.get("/year/{year}/buffer")
def get_year_buffer(year: int, window: int = 2):
    return {y: _build_year_data(y) for y in range(year - window, year + window + 1)}
```

### After (hardened)

```python
import datetime
from fastapi import Path, Query, HTTPException

_CURRENT_YEAR: int = datetime.date.today().year  # fix the hardcoded 2025 too
_MAX_YEAR = 2359
_MIN_YEAR = 0
_MAX_WINDOW = 5

def _validated_year(year: int) -> int:
    if not (_MIN_YEAR <= year <= _MAX_YEAR):
        raise HTTPException(
            status_code=422,
            detail=f"year must be between {_MIN_YEAR} and {_MAX_YEAR}",
        )
    return year

@app.get("/year/{year}")
def get_year(
    year: int = Path(..., ge=_MIN_YEAR, le=_MAX_YEAR,
                     description="Military-time year (0–2359)")
):
    return _build_year_data(year)

@app.get("/year/{year}/buffer")
def get_year_buffer(
    year: int = Path(..., ge=_MIN_YEAR, le=_MAX_YEAR,
                     description="Military-time year (0–2359)"),
    window: int = Query(default=2, ge=1, le=_MAX_WINDOW,
                        description="Number of years either side (max 5)"),
):
    return {y: _build_year_data(y) for y in range(year - window, year + window + 1)}
```

**Why `Path()` + `Query()` over a manual check:** FastAPI validates these constraints at the OpenAPI schema layer *and* at runtime, and they are automatically documented in `/docs`. The `ge`/`le` arguments reject out-of-range values with a structured 422 before any application logic runs. The worst-case amplification is now `2 × 5 + 1 = 11` iterations, not 40,002.

---

## 2. Fix All `innerHTML` XSS Points

**Round 001 finding:** Four `innerHTML` assignments in `index.html` inject unsanitised user-controlled or API-controlled strings.

### Injection point inventory

| Line | Code | Data source | Risk |
|------|------|-------------|------|
| 704 | `elSource.innerHTML = srcHtml + counterHtml` | API `source` + `sourceUrl` fields | Medium — URL could contain `javascript:` |
| 906 | `chip.innerHTML = \`🏷️ ${ct.label} <span ... data-name="${ct.label}">\`` | `localStorage` custom topic label | Medium — stored XSS |
| 1013–1023 | `list.innerHTML = saved.map(s => \`...<div>${s.text}</div>\`)` | `localStorage` saved fact text + source | Medium — stored XSS |
| 1070–1077 | `list.innerHTML = top10.map(e => \`...\${e.name}...\`)` | `EPOCHS` static data | Low — static, but still good practice |

### The `sanitise()` helper

Add this function **once**, near the top of the `<script>` block, before any render functions:

```js
/**
 * Escape a string for safe insertion into HTML text or attribute contexts.
 * Uses the browser's own DOM parser — no regex, no missed edge-cases.
 */
function sanitise(str) {
  const el = document.createElement('span');
  el.textContent = String(str ?? '');
  return el.innerHTML;
  // e.g. sanitise('<img src=x onerror=alert(1)>') → '&lt;img src=x onerror=alert(1)&gt;'
}

/**
 * Sanitise a URL: allow only http/https/# schemes.
 * Returns '#' for anything that looks like javascript: or data: etc.
 */
function sanitiseUrl(url) {
  if (!url) return '#';
  const trimmed = String(url).trim();
  if (/^https?:\/\//i.test(trimmed) || trimmed === '#') return trimmed;
  return '#';
}
```

### Line 704 — source display

```js
// BEFORE (vulnerable to javascript: URL and HTML in source name)
const srcHtml = source
  ? `Source: <a href="${sourceUrl || '#'}" target="_blank" rel="noopener">${source}</a>`
  : '';
const counterHtml = counter ? ` <span style="opacity:0.5;font-size:0.85em">(${counter})</span>` : '';
elSource.innerHTML = srcHtml + counterHtml;

// AFTER
const srcHtml = source
  ? `Source: <a href="${sanitiseUrl(sourceUrl)}" target="_blank" rel="noopener noreferrer">${sanitise(source)}</a>`
  : '';
const counterHtml = counter
  ? ` <span style="opacity:0.5;font-size:0.85em">(${sanitise(counter)})</span>`
  : '';
elSource.innerHTML = srcHtml + counterHtml;
```

### Line 906 — custom topic chip

```js
// BEFORE (stored XSS via label)
chip.innerHTML = `🏷️ ${ct.label} <span class="chip-remove" data-name="${ct.label}">✕</span>`;

// AFTER
chip.innerHTML = `🏷️ ${sanitise(ct.label)} <span class="chip-remove" data-name="${sanitise(ct.label)}">✕</span>`;
```

### Lines 1013–1023 — saved facts panel

```js
// BEFORE (s.text and s.source are localStorage strings — not sanitised)
list.innerHTML = saved.map(s => {
  const reaction = getReaction(s.year, s.text);
  const reactionBadge = reaction === 'like' ? ' 👍' : reaction === 'dislike' ? ' 👎' : '';
  return `
    <div class="saved-item" data-key="${s.key.replace(/"/g, '&quot;')}">
      <button class="saved-item-remove" title="Remove">✕</button>
      <div class="saved-item-year">Year ${s.year}${s.source ? ' · ' + s.source : ''}${reactionBadge}</div>
      <div class="saved-item-text">${s.text}</div>
    </div>
  `;
}).join('');

// AFTER — sanitise every user-controlled field
list.innerHTML = saved.map(s => {
  const reaction = getReaction(s.year, s.text);
  const reactionBadge = reaction === 'like' ? ' 👍' : reaction === 'dislike' ? ' 👎' : '';
  const safeKey = sanitise(s.key);
  const safeSource = s.source ? ' · ' + sanitise(s.source) : '';
  return `
    <div class="saved-item" data-key="${safeKey}">
      <button class="saved-item-remove" title="Remove">✕</button>
      <div class="saved-item-year">Year ${sanitise(s.year)}${safeSource}${reactionBadge}</div>
      <div class="saved-item-text">${sanitise(s.text)}</div>
    </div>
  `;
}).join('');
```

### Lines 1070–1077 — era stats panel (defence-in-depth)

```js
// BEFORE
list.innerHTML = top10.map(e => `
  <div class="saved-item">
    <div class="saved-item-year">${e.name}</div>
    <div class="saved-item-text" style="font-size:0.8rem;color:var(--text-muted)">
      Shown: ${e.count} &bull; Weight: ${e.weight} &bull; Score: ${e.score.toFixed(2)}
    </div>
  </div>
`).join('');

// AFTER — era names come from EPOCHS (static), but wrap anyway
list.innerHTML = top10.map(e => `
  <div class="saved-item">
    <div class="saved-item-year">${sanitise(e.name)}</div>
    <div class="saved-item-text" style="font-size:0.8rem;color:var(--text-muted)">
      Shown: ${sanitise(e.count)} &bull; Weight: ${sanitise(e.weight)} &bull; Score: ${sanitise(e.score.toFixed(2))}
    </div>
  </div>
`).join('');
```

---

## 3. CSP Header Proposal

**Round 001 finding:** No `Content-Security-Policy` header is set anywhere. Any future XSS has unlimited blast radius.

**Prerequisite:** The entire app JS lives in an inline `<script>` block. To gain meaningful `script-src` protection, that block must either be moved to an external `app.js` file (enabling `'self'`) or be accompanied by a server-generated `nonce`. The nonce approach is shown below.

### For the FastAPI service (API responses)

```python
# main.py — add this middleware above the CORS middleware
from starlette.middleware.base import BaseHTTPMiddleware

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "geolocation=(), camera=(), microphone=()"
        # API responses are JSON — no scripts allowed at all
        response.headers["Content-Security-Policy"] = "default-src 'none'"
        return response

app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(CORSMiddleware, ...)  # keep CORS below security headers
```

### For a static nginx deployment (the HTML/JS app)

Move `index.html`'s `<script>` block to `app.js`, then set:

```nginx
# nginx.conf — server block
add_header Content-Security-Policy
  "default-src 'none'; \
   script-src 'self'; \
   style-src 'self' 'unsafe-inline'; \
   connect-src 'self' https://query.wikidata.org; \
   img-src 'self' data:; \
   font-src 'self'; \
   frame-ancestors 'none'; \
   base-uri 'self'; \
   form-action 'none';"
  always;
add_header X-Content-Type-Options "nosniff" always;
add_header X-Frame-Options "DENY" always;
add_header Referrer-Policy "strict-origin-when-cross-origin" always;
```

### Directive-by-directive explanation

| Directive | Value | Reason |
|-----------|-------|--------|
| `default-src` | `'none'` | Deny everything not explicitly allowed — safest baseline |
| `script-src` | `'self'` | Only load scripts from same origin; blocks injected `<script src="evil.com">` |
| `style-src` | `'self' 'unsafe-inline'` | Inline styles are used pervasively (CSS vars); move to external file to drop `'unsafe-inline'` |
| `connect-src` | `'self' https://query.wikidata.org` | Allows `fetch()` to the FastAPI backend and Wikidata only |
| `img-src` | `'self' data:` | `data:` needed for the clock SVG/canvas |
| `frame-ancestors` | `'none'` | Blocks clickjacking — equivalent to `X-Frame-Options: DENY` |
| `base-uri` | `'self'` | Blocks `<base href>` injection attacks |
| `form-action` | `'none'` | No `<form>` submissions in this app |

---

## 4. CORS Tightening

**Round 001 finding:** `allow_origins=["*"]` allows any website to `POST /reaction`, `POST /saved`, or `DELETE /saved/{key}` — polluting or wiping the database via cross-origin requests.

**When to tighten:** Immediately if the service is exposed beyond `localhost`. Proactively now, to build the habit.

```python
# main.py

import os

def _get_allowed_origins() -> list[str]:
    """
    Read allowed CORS origins from the CORS_ORIGINS env var (comma-separated).
    Falls back to localhost dev URLs so local development continues to work.
    Example: CORS_ORIGINS="https://yearclock.example.com,https://app.internal"
    """
    raw = os.environ.get("CORS_ORIGINS", "")
    if raw.strip():
        origins = [o.strip() for o in raw.split(",") if o.strip()]
        return origins
    # Default: safe for local development only
    return [
        "http://localhost",
        "http://localhost:8421",
        "http://127.0.0.1",
        "http://127.0.0.1:8421",
        "null",  # file:// origin used when opening index.html directly
    ]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_get_allowed_origins(),
    allow_methods=["GET", "POST", "DELETE"],  # enumerate — not "*"
    allow_headers=["Content-Type"],           # enumerate — not "*"
    allow_credentials=False,                  # explicit; never set True with a broad origin list
)
```

**Deployment:** Set `CORS_ORIGINS` in your `.env` or `docker-compose.yml`:

```env
CORS_ORIGINS=https://yearclock.yourhost.com
```

---

## 5. Rate Limiting

**Round 001 finding:** No rate limiting exists. A bot can hammer `/year/{year}` for all 2,360 years, exhausting Wikidata quota and getting the server's IP banned.

### Option A — `slowapi` (recommended, production-grade)

```bash
pip install slowapi
```

```python
# main.py
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

@app.get("/year/{year}")
@limiter.limit("60/minute")   # 1 req/s sustained, burst of 60
def get_year(
    request: Request,  # slowapi requires Request as first param
    year: int = Path(..., ge=0, le=2359),
):
    return _build_year_data(year)

@app.get("/year/{year}/buffer")
@limiter.limit("10/minute")   # buffer is heavier — stricter limit
def get_year_buffer(
    request: Request,
    year: int = Path(..., ge=0, le=2359),
    window: int = Query(default=2, ge=1, le=5),
):
    return {y: _build_year_data(y) for y in range(year - window, year + window + 1)}

@app.post("/reaction", status_code=201)
@limiter.limit("30/minute")
def post_reaction(request: Request, body: ReactionBody):
    ...

@app.post("/saved", status_code=201)
@limiter.limit("30/minute")
def post_saved(request: Request, body: SaveBody):
    ...

@app.delete("/saved/{key}")
@limiter.limit("30/minute")
def delete_saved(request: Request, key: str):
    ...
```

### Option B — simple in-memory counter (zero dependencies)

For environments where adding a dependency is not desired:

```python
# main.py — append before routes
import time
from collections import defaultdict
from threading import Lock

_rate_store: dict[str, list[float]] = defaultdict(list)
_rate_lock = Lock()

def _check_rate(key: str, max_calls: int, window_seconds: int = 60) -> None:
    """Raise 429 if `key` has exceeded `max_calls` in the last `window_seconds`."""
    now = time.monotonic()
    cutoff = now - window_seconds
    with _rate_lock:
        calls = _rate_store[key]
        # Evict old timestamps
        _rate_store[key] = [t for t in calls if t > cutoff]
        if len(_rate_store[key]) >= max_calls:
            raise HTTPException(status_code=429, detail="Too many requests")
        _rate_store[key].append(now)

# Usage in a route:
@app.get("/year/{year}/buffer")
def get_year_buffer(
    request: Request,
    year: int = Path(..., ge=0, le=2359),
    window: int = Query(default=2, ge=1, le=5),
):
    _check_rate(request.client.host, max_calls=10, window_seconds=60)
    return {y: _build_year_data(y) for y in range(year - window, year + window + 1)}
```

> **Note:** Option B is single-process only. If uvicorn is run with multiple workers (`--workers 4`), each worker has an independent counter, so the effective limit is `max_calls × workers`. Use `slowapi` backed by Redis for multi-worker deployments.

---

## 6. Input Validation for Year (Pydantic + Path)

**Round 001 finding:** `/year/{year}` and the `ReactionBody`/`SaveBody` models accept any integer, including negatives and values far above 2359.

The `Path()` constraints in §1 handle the URL path. For the request bodies:

```python
from pydantic import BaseModel, field_validator

_YEAR_MIN = 0
_YEAR_MAX = 2359

class ReactionBody(BaseModel):
    year: int
    text: str
    source: str | None = None
    reaction: str  # 'like' or 'dislike'

    @field_validator('year')
    @classmethod
    def year_in_range(cls, v: int) -> int:
        if not (_YEAR_MIN <= v <= _YEAR_MAX):
            raise ValueError(f'year must be between {_YEAR_MIN} and {_YEAR_MAX}')
        return v

    @field_validator('text')
    @classmethod
    def text_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError('text must not be blank')
        if len(v) > 2000:
            raise ValueError('text exceeds maximum length of 2000 characters')
        return v.strip()

    @field_validator('reaction')
    @classmethod
    def reaction_valid(cls, v: str) -> str:
        if v not in ('like', 'dislike'):
            raise ValueError("reaction must be 'like' or 'dislike'")
        return v


class SaveBody(BaseModel):
    year: int
    text: str
    source: str | None = None

    @field_validator('year')
    @classmethod
    def year_in_range(cls, v: int) -> int:
        if not (_YEAR_MIN <= v <= _YEAR_MAX):
            raise ValueError(f'year must be between {_YEAR_MIN} and {_YEAR_MAX}')
        return v

    @field_validator('text')
    @classmethod
    def text_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError('text must not be blank')
        if len(v) > 2000:
            raise ValueError('text exceeds maximum length of 2000 characters')
        return v.strip()
```

All Pydantic validation errors are automatically returned by FastAPI as structured 422 responses with field-level detail — no custom error handling required.

---

## 7. Dependency Audit

**Round 001 finding:** `requirements.txt` is unpinned. A future `pip install` may pull a vulnerable version.

### Step-by-step process

```bash
# 1. Pin current working versions
cd clockapp/server
pip freeze > requirements.lock
# Commit requirements.lock — this is the reproducible install manifest
git add requirements.lock
git commit -m "chore: pin Python dependencies"

# 2. Audit against known CVE databases (PyPA + OSV)
pip install pip-audit
pip-audit -r requirements.lock
# Or scan the currently installed environment:
pip-audit

# 3. (Optional) Generate SBOM for supply-chain tracking
pip install cyclonedx-bom
cyclonedx-py requirements requirements.lock --outfile sbom.json

# 4. For the web app — no npm packages are used today (vanilla JS PWA).
#    If a package.json is ever added:
npm audit --audit-level=moderate
npm audit fix
```

### Keeping deps updated

1. **GitHub Dependabot** — add `.github/dependabot.yml`:

```yaml
version: 2
updates:
  - package-ecosystem: pip
    directory: "/clockapp/server"
    schedule:
      interval: weekly
    open-pull-requests-limit: 5
```

2. **CI gate** — add `pip-audit -r requirements.lock --fail-on-vuln` to your GitHub Actions workflow so a CVE in a dep blocks merges automatically.

3. **Pinning strategy** — pin transitive deps in `requirements.lock`, keep the human-readable `requirements.txt` with loose version constraints (e.g., `fastapi>=0.115,<1.0`), and update `requirements.lock` via `pip-compile` (from `pip-tools`) weekly.

---

## 8. localStorage Integrity Check

**Round 001 finding:** `localStorage` data is read and injected into the DOM without any schema validation. A tampered or corrupt entry could trigger XSS or a runtime crash.

### Minimal schema validator + graceful fallback

Add this near the top of the `<script>` block, before any `loadX()` calls:

```js
/**
 * Validates and loads a localStorage key.
 * @param {string} key - localStorage key
 * @param {Function} validator - returns true if the parsed value is valid
 * @param {*} fallback - returned if missing, unparseable, or invalid
 */
function loadValidated(key, validator, fallback) {
  try {
    const raw = localStorage.getItem(key);
    if (raw === null) return fallback;
    const parsed = JSON.parse(raw);
    if (!validator(parsed)) {
      console.warn(`[clockapp] localStorage "${key}" failed validation — resetting.`);
      localStorage.removeItem(key);
      return fallback;
    }
    return parsed;
  } catch (err) {
    console.warn(`[clockapp] localStorage "${key}" is corrupt — resetting.`, err);
    localStorage.removeItem(key);
    return fallback;
  }
}

// ── Validators ─────────────────────────────────────────────────────────────────

function isValidCustomTopics(v) {
  return Array.isArray(v) && v.every(t =>
    t !== null &&
    typeof t === 'object' &&
    typeof t.label === 'string' &&
    t.label.length > 0 &&
    t.label.length <= 100 &&
    Array.isArray(t.keywords) &&
    t.keywords.every(k => typeof k === 'string')
  );
}

function isValidSaved(v) {
  return Array.isArray(v) && v.every(s =>
    s !== null &&
    typeof s === 'object' &&
    typeof s.year === 'number' &&
    s.year >= 0 &&
    s.year <= 2359 &&
    typeof s.text === 'string' &&
    s.text.length > 0 &&
    s.text.length <= 2000 &&
    typeof s.key === 'string'
  );
}

function isValidReactions(v) {
  return typeof v === 'object' && v !== null && !Array.isArray(v) &&
    Object.entries(v).every(([k, r]) =>
      typeof k === 'string' && (r === 'like' || r === 'dislike')
    );
}

// ── Updated loaders ────────────────────────────────────────────────────────────

function loadCustomTopics() {
  return loadValidated('clockapp-custom-topics', isValidCustomTopics, []);
}

function loadSaved() {
  return loadValidated('clockapp-saved', isValidSaved, []);
}

function loadReactions() {
  return loadValidated('clockapp-reactions', isValidReactions, {});
}
```

**What this buys you:**
- Corrupt JSON (e.g., truncated write due to storage quota) is caught and reset silently.
- An injected entry with a `text` field exceeding 2000 chars is rejected before it reaches `sanitise()`.
- The validators are the single source of truth for what each store should look like — updating them is the first step before adding any new stored field.

---

## 9. Threat Model Summary

| Asset | Threat | Attacker | Mitigation | Residual Risk |
|-------|--------|----------|------------|---------------|
| **Wikidata API quota** | DoS amplification via `/buffer?window=N` | Unauthenticated bot | Cap `window=5`, rate-limit 10/min per IP (§1, §5) | Low — capped at 11 requests per call |
| **Server availability** | CPU/memory exhaustion from large `window` | Unauthenticated bot | `window` cap + rate limiting | Low |
| **User saved facts** | Cross-origin deletion via `DELETE /saved/{key}` | Malicious website visited by user | Tighten CORS to known origins (§4); add API key if network-exposed | Medium if ever network-exposed |
| **User saved facts** | Stored XSS via `localStorage` tampering | Malicious browser extension | `sanitise()` helper on all innerHTML (§2), localStorage schema validation (§8) | Low — no script execution possible post-sanitisation |
| **User privacy** | IP address leak via direct Wikidata fetch in web client | Wikidata log analysis | Wire web client to FastAPI proxy (tracked in Round 001 backlog) | High — architectural change needed |
| **Supply chain** | Vulnerable transitive Python dependency | Compromised PyPI package | Pin deps to `requirements.lock`, `pip-audit` in CI (§7) | Low with Dependabot + audit gate |
| **XSS blast radius** | Injected script exfiltrates to attacker server | XSS payload author | CSP `connect-src 'self' https://query.wikidata.org` (§3) | Low with CSP deployed |
| **SPARQL injection** | Malicious year value in SPARQL query | Unauthenticated API caller | Python `int` type enforces; year bounded 0–2359 (§1, §6) | None — structurally impossible |
| **Data confidentiality** | Unauthenticated `GET /saved` dumps all saved facts | Anyone with network access | API key header check if network-exposed (§8 in Round 001) | Low on localhost; High if exposed |
| **SQLite file access** | Other OS users read `~/.clockapp/yearclock.db` | Local OS user | `mkdir(mode=0o700)` for `~/.clockapp/` (Round 001 §9) | Low on single-user machine |

---

## 10. Security Backlog — Prioritised GitHub Issue Titles

Ordered by severity (P1 = must fix, P4 = nice to have):

| Priority | Issue title | Maps to |
|----------|-------------|---------|
| **P1** | `security: cap /buffer window to 5 and add year bounds 0–2359 via Path()/Query()` | §1 + §6 |
| **P1** | `security: add per-IP rate limiting to /year, /buffer, /reaction, /saved endpoints` | §5 |
| **P1** | `security: sanitise all innerHTML injection points with sanitise() helper` | §2 |
| **P1** | `fix: replace hardcoded _CURRENT_YEAR=2025 with datetime.date.today().year` | Cross-cutting |
| **P2** | `security: tighten CORS to configurable origin list via CORS_ORIGINS env var` | §4 |
| **P2** | `security: add Content-Security-Policy header to nginx and FastAPI middleware` | §3 |
| **P2** | `security: add localStorage schema validation with graceful fallback on load` | §8 |
| **P2** | `security: pin Python deps to requirements.lock and add pip-audit to CI` | §7 |
| **P3** | `security: add X-Content-Type-Options, X-Frame-Options, Referrer-Policy headers` | §3 |
| **P3** | `security: restrict mkdir for ~/.clockapp to mode 0o700 (multi-user systems)` | Round 001 §9 |
| **P3** | `security: add API key guard (X-API-Key header) for network-exposed deployments` | Round 001 §8 |
| **P3** | `chore: enable GitHub Dependabot for Python ecosystem` | §7 |
| **P4** | `refactor: move inline <script> block to app.js to enable strict CSP script-src 'self'` | §3 prerequisite |
| **P4** | `security: wire web client to FastAPI proxy to eliminate direct Wikidata IP leak` | Round 001 §2 |
| **P4** | `security: add pip-audit --fail-on-vuln step to GitHub Actions CI workflow` | §7 |

---

## Summary of Changes Required

```
server/main.py      — Path()/Query() constraints, CORS env var, SecurityHeadersMiddleware,
                      slowapi rate limiting, _CURRENT_YEAR fix, Pydantic validators
web/index.html      — sanitise() + sanitiseUrl() helpers, apply to 4 innerHTML sites,
                      loadValidated() + schema validators for 3 localStorage keys
nginx.conf (new)    — Content-Security-Policy, X-Content-Type-Options, X-Frame-Options
.github/dependabot.yml (new) — weekly pip audit PRs
requirements.lock (new)      — pinned transitive deps from pip freeze
```

All mitigations in P1 and P2 can be completed in a single afternoon sprint. No architectural changes are required for any of them.
