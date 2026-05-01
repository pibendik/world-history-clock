# Year Clock — Security Review (Round 001)

**Scope:** `clockapp/server/main.py`, `clockapp/server/db.py`, `clockapp/server/fetcher.py`, `clockapp/web/index.html`  
**Reviewer role:** Application security champion  
**Date:** 2025-07-01

---

## 1. CORS Wildcard (`allow_origins=["*"]`)

**Location:** `main.py` lines 23–28

```python
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
```

**Real risk for this use case:**  
CORS `*` means *any* origin can make cross-origin requests to the API. For a purely read API with no cookies or auth headers, this is low risk — browsers enforce `*` cannot be combined with `credentials: true`, so session-hijacking via CSRF is not possible.

**When it becomes a problem:**
- If authentication (e.g., session cookies, `Authorization` headers) is ever added, a `*` wildcard silently breaks `credentials: true` — developers may then widen it to `allow_credentials=True` *and* a specific origin list, but a future developer might also accidentally set `allow_origins=["*"]` + `allow_credentials=True`, which FastAPI will allow — resulting in a browser CORS bypass vector.
- The `POST /reaction`, `POST /saved`, and `DELETE /saved/{key}` endpoints mutate server state. Any website the user visits can silently POST to these endpoints and pollute the database. An attacker could craft a page that mass-posts garbage reactions/saves or bulk-deletes all saved facts (`DELETE /saved/{key}` just needs a guessable or enumerated key).
- The key format is `{year}::{text}`, which is deterministic and trivially guessable for popular facts. A cross-origin script can enumerate and delete all saved facts for a target user.

**Risk:** Medium (low for data confidentiality; medium for integrity abuse of write endpoints).

---

## 2. Custom Topic Keyword Injection

**Location:** `index.html` lines 906, 1095–1103

```js
chip.innerHTML = `🏷️ ${ct.label} <span class="chip-remove" data-name="${ct.label}">✕</span>`;
```

**Stored XSS via localStorage:**  
When a user saves a custom topic, the `label` is stored in `localStorage` and later injected verbatim into `innerHTML`. If an attacker can write arbitrary content to `localStorage['clockapp-custom-topics']` (e.g., via a cross-origin script on the same origin, or via developer tools / browser extension compromise), a payload like:

```
label: "<img src=x onerror=alert(document.cookie)>"
```

…will execute in the context of the page. This is a **self-XSS** in the normal case (user must inject their own storage), but becomes a real stored XSS if:

- A browser extension with `storage` permission writes to the origin's localStorage.
- A future feature exports/imports topic lists from a URL parameter or shared link.

The `data-name="${ct.label}"` attribute inside the injected HTML is also unescaped, creating a second injection point via attribute injection.

**Keyword injection into filtering:** Keywords are only used for client-side `.includes(kw)` string matching against event text — there is no server-side injection surface today.

**SPARQL injection (server-side, theoretical):** The server's `fetcher.py` constructs SPARQL via `template.format(year=year)` where `year` is a Python `int` — it is structurally impossible to inject SPARQL through the year parameter server-side. However, if keywords were ever forwarded to the server and embedded into a SPARQL query template, they would be a direct injection surface because the Wikidata SPARQL endpoint is not parametrised.

**Risk:** Low (currently self-XSS only). Medium if topic import/export is added without sanitisation.

---

## 3. localStorage Trust Model

**Location:** `index.html` — reactions, saved facts, era exposure, active topic, custom topics all persisted to `localStorage`.

**Threat model:**

| Store key | Data stored | Tamper impact |
|---|---|---|
| `clockapp-reactions` | `{year, text, reaction}` objects | UI reaction state corrupted |
| `clockapp-saved` | `{year, text, source, key}` objects | Saved panel XSS if `text` or `source` contain HTML (see §2 + §6 below) |
| `clockapp-era-exposure` | `{eraName: count}` | Stats panel shows wrong data |
| `clockapp-custom-topics` | `{label, keywords[]}` | Stored XSS via `innerHTML` injection (§2) |
| `clockapp-topic` | topic name string | Silently switches active filter |

**Can an attacker tamper?**  
From a different origin: No, `localStorage` is same-origin isolated by the browser.  
From the same origin: Yes — any JS running on the same page origin can overwrite all keys. This includes browser extensions with `content_scripts` permission targeting `*://*/*` (extremely common extensions like ad blockers, password managers, etc. can do this).

**Impact:** Low confidentiality impact (no secrets stored). Medium integrity impact — particularly the `clockapp-saved` XSS path: a malicious extension writes a crafted `clockapp-saved` entry with `text: "<script>..."`, then when `renderSavedPanel()` runs, it executes because `list.innerHTML = saved.map(...)` does not sanitise `s.text` (line 1020: `<div class="saved-item-text">${s.text}</div>`).

**Risk:** Low–Medium.

---

## 4. Input Validation — Year Parameter

**Location:** `main.py` line 76 and 81

```python
@app.get("/year/{year}")
def get_year(year: int):
    return _build_year_data(year)

@app.get("/year/{year}/buffer")
def get_year_buffer(year: int, window: int = 2):
    return {y: _build_year_data(y) for y in range(year - window, year + window + 1)}
```

**`/year/abc`:** FastAPI's `int` path parameter type causes a 422 Unprocessable Entity response automatically. Safe.

**`/year/99999`:** Accepted without bounds checking. `_build_year_data(99999)` will:
1. Call `get_events_for_year(99999)` → `fetch_wikidata_events(99999)` → two live HTTP requests to Wikidata for a year that has no results. This is a **server-side request to an external service triggered by an unauthenticated user**, burning Wikidata quota and the server's outbound bandwidth.
2. Call `increment_era_exposure(eras[0]["name"])` — if `eras` is empty (it will be for year 99999), this is guarded by `if eras:`, so no crash. Safe.

**`/year/0` or negative years:** No lower bound either. Year `-9999` would fire Wikidata queries for a BC year (Wikidata uses `xsd:dateTime` which does handle negative years in some cases).

**`/year/{year}/buffer` amplification:** `window` is a query parameter with default 2. A caller can send `/year/1000/buffer?window=10000`, causing `range(-9000, 11001)` = 20,001 iterations, each calling `_build_year_data` and potentially issuing up to 2 × 20,001 = 40,002 Wikidata HTTP requests in a single API call. This is a **server-side request forgery / DoS amplification** vector.

**Risk:** High (for the buffer endpoint amplification). Low (for single year out-of-range).

---

## 5. SPARQL Injection — Is It Actually Possible?

**Location:** `fetcher.py` lines 34, 35

```python
query = template.format(year=year).strip()
```

The `year` variable is typed as `int` in FastAPI. Python's `int` cannot contain SPARQL-injectable characters (quotes, braces, semicolons). The format string substitution produces e.g. `FILTER(YEAR(?date) = 1492)` — a clean integer literal.

**Conclusion: SPARQL injection is not possible through the year parameter as currently implemented.** The type system provides a hard guarantee: if FastAPI accepts the request, `year` is already a Python `int`, and `str(int)` can only produce digits and an optional leading minus sign.

**Future risk to document:** If keywords from custom topics are ever sent server-side and embedded in SPARQL (e.g., `FILTER(CONTAINS(STR(?eventLabel), "${keyword}"))`), that would be a direct SPARQL injection vector because string template substitution is used. Keywords can contain `"`, `\`, and SPARQL metacharacters. Mitigation would require either parameterised queries (Wikidata SPARQL endpoint does not support bind parameters) or strict allowlisting/escaping of keyword characters before interpolation.

**Risk:** None currently. High if keywords migrate server-side without sanitisation.

---

## 6. CSP Headers

**Location:** Neither `main.py` nor the HTML `<head>` set a `Content-Security-Policy` header.

**What is missing and what it enables:**

- No `default-src` restriction — any injected `<script>` tag will execute.
- No `script-src` — inline `<script>` blocks run (the entire app JS is an inline script block). A future XSS payload can also inject new scripts from any origin.
- No `connect-src` — the app makes cross-origin fetch requests to `https://query.wikidata.org` and to the FastAPI backend (localhost or wherever). Without a `connect-src` directive, XSS payloads can exfiltrate data to arbitrary external servers.
- No `style-src` — injected `<style>` or `style=` attributes execute.

**Recommended CSP for the web app** (served as a static file, assuming API at same host or explicit domain):

```
Content-Security-Policy:
  default-src 'none';
  script-src 'self' 'nonce-{random}';
  style-src 'self' 'unsafe-inline';
  connect-src 'self' https://query.wikidata.org;
  img-src 'self' data:;
  font-src 'self';
  frame-ancestors 'none';
  base-uri 'self';
  form-action 'none';
```

Because the entire application script is inline, moving it to an external file and using `'self'` (or a nonce) for `script-src` is a prerequisite to gaining meaningful XSS protection.

**FastAPI CSP header** (add to `main.py`):

```python
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Content-Security-Policy"] = "default-src 'none'"
        return response
```

**Risk:** Medium — no exploitable XSS exists today, but the absence of CSP means any future XSS (see §2, §3) has maximum blast radius.

---

## 7. Dependency Security

**Pinned versions:** `requirements.txt` files use unpinned names (`fastapi`, `uvicorn[standard]`, `requests`, `pydantic`). The installed versions in the venv are:

- `requests 2.33.1` — current as of 2025-06; no known active CVEs.
- `fastapi` + `pydantic` v2 — current series, no known critical CVEs.
- `uvicorn` — check with `pip show uvicorn` for version.

**Risks from unpinned dependencies:**
- A `pip install` on a new machine may pull a different (newer or older) version. If a vulnerability is introduced in a future release and dependencies are not pinned, `pip install -r requirements.txt` will silently upgrade to the vulnerable version.
- Supply-chain attack: a typosquatted or hijacked package on PyPI matching an unpinned requirement can be pulled automatically.

**Recommended actions:**
1. Pin all dependencies with `pip freeze > requirements.lock` and use `pip install -r requirements.lock` in production.
2. Add `pip-audit` to CI: `pip install pip-audit && pip-audit -r requirements.txt` scans against OSV/PyPA advisory databases.
3. Enable GitHub Dependabot for the Python ecosystem on this repository.

**Risk:** Low currently (no known CVEs in installed versions). Medium risk posture due to unpinned deps.

---

## 8. No Authentication

**Location:** All endpoints in `main.py` are publicly accessible with no authentication or authorisation.

**What any unauthenticated caller can do:**

| Endpoint | Read / Write | Data exposed or mutated |
|---|---|---|
| `GET /year/{year}` | Read | Triggers Wikidata fetch, increments era exposure |
| `GET /year/{year}/buffer` | Read | Amplified Wikidata fetches (see §4) |
| `GET /reactions` | Read | Full dump of all reaction history (year + event text) |
| `GET /saved` | Read | Full dump of all saved facts |
| `POST /reaction` | Write | Inject arbitrary reactions with any year/text/source |
| `POST /saved` | Write | Inject arbitrary facts into the saved list |
| `DELETE /saved/{key}` | Write | Delete any saved fact by key |
| `GET /eras` | Read | Era exposure statistics |

**Practical impact today:** The service is intended to run on `localhost`. If it is ever exposed to the network (e.g., on a home server, in Docker without a firewall, or via ngrok/Tailscale), any person on that network can read, inject, and delete the user's personal fact collection and reaction history. The `DELETE /saved/{key}` endpoint is particularly destructive: keys are deterministic (`{year}::{text}`), and `GET /saved` leaks all existing keys first, making a wipe script trivial.

**Recommendation:** If this ever runs beyond localhost, add at minimum an API key header check (`X-API-Key`) via a FastAPI dependency.

**Risk:** Low on localhost. High if network-exposed.

---

## 9. SQLite Path Safety

**Location:** `db.py` line 8

```python
_DB_PATH = Path.home() / ".clockapp" / "yearclock.db"
```

**Path traversal:** The path is constructed from `Path.home()` (a fixed system value) plus two hardcoded string components. There is no user-controlled input in the path construction. Path traversal is **not possible** here.

**Security of the location:**
- `~/.clockapp/` is created with `mkdir(exist_ok=True)` without explicit permission bits, so it inherits the default umask (typically `0o755` on Linux). The `.db` file itself is created by SQLite and defaults to `0o644`. This means other users on a multi-user system can read the database file, exposing all saved facts, reactions, and era exposure data.
- Recommended: `_DB_PATH.parent.mkdir(mode=0o700, exist_ok=True)` to restrict the directory to owner-only access.

**Risk:** Low (single-user workstation). Low–Medium on multi-user systems.

---

## 10. Rate Limiting

**Location:** `main.py` — no rate limiting middleware anywhere.

**Abuse scenarios:**

1. **Wikidata quota exhaustion:** The `/year/{year}` endpoint triggers up to 2 Wikidata HTTP requests per uncached year. Wikidata enforces a rate limit of ~1 req/s per IP for anonymous queries. A bot hammering `/year/N` for N = 1..2359 would issue 4,718 Wikidata requests from the server's IP, potentially getting the server's IP rate-limited or temporarily banned by Wikidata.
2. **Buffer amplification DoS** (also covered in §4): A single request to `/year/1000/buffer?window=5000` generates ~10,000 iterations.
3. **Database bloat:** `POST /reaction` and `POST /saved` insert rows without a per-user quota. A script can fill the SQLite database with millions of rows, consuming disk space and degrading read performance.
4. **CPU/memory:** Each `/year/{year}/buffer` response builds a large dict in memory. With `window=10000`, the response JSON could exceed hundreds of MB.

**Recommendation:** Add `slowapi` (the FastAPI rate-limiting library) to cap per-IP requests:

```python
from slowapi import Limiter
from slowapi.util import get_remote_address
limiter = Limiter(key_func=get_remote_address)

@app.get("/year/{year}")
@limiter.limit("30/minute")
def get_year(year: int, request: Request): ...
```

Also add a hard cap on `window` parameter: `window: int = Query(default=2, ge=0, le=10)`.

**Risk:** Medium.

---

## 11. Privacy — Wikidata Requests from the Browser

**Location:** `index.html` lines 721–729 — the browser makes direct `fetch()` calls to `https://query.wikidata.org/sparql`.

```js
const url = `https://query.wikidata.org/sparql?format=json&query=${encodeURIComponent(sparql)}`;
const resp = await fetch(url, { headers: { Accept: 'application/sparql-results+json' } });
```

**What Wikidata sees:**
- The user's real public IP address (not the server's IP — these are browser-initiated requests).
- The `User-Agent` string of the user's browser (Chrome/Firefox + OS + version).
- The exact SPARQL query, which encodes the year being viewed (and therefore the current time, since year = HH×100+MM).
- `Referer` header (browser may send the app's URL).

**Privacy implications:**
- Wikidata/Wikimedia Foundation logs these queries. Their privacy policy applies, but the user has not been informed of this third-party data sharing.
- A passive network observer (ISP, corporate firewall, coffee-shop Wi-Fi) can see the destination host (`query.wikidata.org`) and infer the user is running the Year Clock app at a known time of day.
- If the app is ever served over HTTPS, the query content is encrypted in transit, but the destination hostname is visible via SNI/DNS.

**The FastAPI server also fetches Wikidata** (via `fetcher.py`) when the browser requests `/year/{year}` — this proxies the request through the server, hiding the user's IP from Wikidata. However, the browser-side fetch path in `index.html` bypasses this proxy and leaks the user's IP directly.

**Recommendation:** Route all Wikidata fetches through the FastAPI backend (browser → local API → Wikidata). This is already the pattern for the server-side cache; the browser-side `fetchWikidata()` function is a fallback path that should either be removed or routed through a local proxy endpoint.

**Risk:** Low (single-user local app). Medium if deployed for multiple users or in a privacy-sensitive context.

---

## 12. Severity Matrix

| # | Finding | Severity | Justification |
|---|---|---|---|
| 1 | CORS wildcard | **Medium** | Write endpoints abusable cross-origin; no auth amplifies this |
| 2 | Custom topic stored XSS via `innerHTML` | **Medium** | Self-XSS today; real XSS if extension compromise or import feature added |
| 3 | localStorage integrity / XSS via saved facts | **Medium** | `s.text` unsanitised in `innerHTML`; extension or self-XSS path exists |
| 4 | Missing year bounds + buffer amplification | **High** | Single unauthenticated request can trigger 40 000 outbound HTTP calls |
| 5 | SPARQL injection (server-side) | **None** | Integer type provides complete protection currently |
| 6 | No CSP headers | **Medium** | Maximises blast radius of any XSS finding |
| 7 | Unpinned dependencies | **Low** | No known CVEs; risk is future supply-chain or upgrade |
| 8 | No authentication | **Low** (localhost) / **High** (network-exposed) | Full read/write/delete without credentials |
| 9 | SQLite path traversal | **None** | Hardcoded path, no user input |
| 9b | SQLite file permissions | **Low** | World-readable on multi-user systems |
| 10 | No rate limiting + buffer DoS | **High** | See §4 and §10; resource exhaustion + Wikidata ban risk |
| 11 | Browser Wikidata IP leak | **Low** | No secrets leaked; privacy concern only |

---

## 13. Top 3 Immediate Security Actions

### 🔴 Action 1 — Cap the `window` parameter and add year bounds (High)

In `main.py`, add a `Query` constraint on `window` and validate year range before calling Wikidata:

```python
from fastapi import Query

@app.get("/year/{year}/buffer")
def get_year_buffer(year: int, window: int = Query(default=2, ge=0, le=10)):
    if not (0 <= year <= 2359):
        raise HTTPException(status_code=422, detail="year must be 0–2359")
    return {y: _build_year_data(y) for y in range(year - window, year + window + 1)}
```

Apply the same bounds check to `/year/{year}`. This eliminates the request-amplification DoS vector with a two-line change.

### 🟠 Action 2 — Sanitise `innerHTML` injection points (Medium)

Replace the three `innerHTML` assignments that render unsanitised user-controlled data:

1. `chip.innerHTML = \`🏷️ ${ct.label}...\`` → use `chip.textContent` for the label and create the `✕` span via `createElement`.
2. `list.innerHTML = saved.map(s => \`...\${s.text}...\`)` → escape `s.text` and `s.source` with a helper:

```js
function esc(s) {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}
```

3. `elSource.innerHTML = srcHtml` (line 704) — `source` and `sourceUrl` come from Wikidata responses; ensure they are escaped or use `createElement('a')` with `.textContent` and `.href`.

### 🟡 Action 3 — Restrict CORS to known origins and add security headers (Medium)

Replace the wildcard with an explicit origin list (or localhost-only for a local app), and add basic security headers to all API responses:

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost", "http://127.0.0.1"],
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Content-Type"],
)
```

Add an `X-Content-Type-Options: nosniff` and `X-Frame-Options: DENY` response middleware, and set a `Content-Security-Policy` on the HTML file (via the web server config or a `<meta>` tag as a stopgap).

---

*End of security review. Total word count: ~1 700 words.*
