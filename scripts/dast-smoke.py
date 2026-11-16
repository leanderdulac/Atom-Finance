"""Authenticated DAST-lite smoke: asserts live security behavior, not features.

Runs against an isolated test deployment (same env as smoke-production.py):
  ATOM_SMOKE_URL, ATOM_SMOKE_USER, ATOM_SMOKE_PASSWORD

Probes (each prints PASS or raises with evidence):
  1. Security headers on /api/health (nosniff, no-referrer, no-store, DENY, HSTS)
  2. No Swagger/OpenAPI markers on the public /docs and /openapi.json
     (prod only; dev keeps backend docs by design)
  3. Auth boundary: protected routes 401 without token and with a garbage token
  4. Real login for the authenticated probes below
  5. No stack traces: 404/400/422 bodies are JSON without "Traceback"
  6. Oversize body: Content-Length > 5MB returns 413 fast (early abort)
  7. CORS: a foreign Origin is never reflected with credentials
  8. /api/health leaks no key material (presence booleans only)
  9. Refresh cookie is HttpOnly + SameSite=Lax (+Secure in production)
  10. Login brute-force limit: bad passwords eventually return 429 (LAST:
      it burns the shared IP bucket, nothing after it needs /login)

Stdlib only. Exits nonzero on the first failure.
"""
import json
import os
import time
from urllib.request import Request, urlopen
from urllib.error import HTTPError

BASE = os.environ.get("ATOM_SMOKE_URL", "http://127.0.0.1:18080")
USER = os.environ["ATOM_SMOKE_USER"]
PASSWORD = os.environ["ATOM_SMOKE_PASSWORD"]
# The stack under test is a production build (docs disabled, Secure cookies).
# Set ATOM_DAST_EXPECT_PROD=1 when that is true (CI containers job does);
# against a dev stack the prod-only probes skip instead of failing.
EXPECT_PROD = os.environ.get("ATOM_DAST_EXPECT_PROD", "").strip().lower() in ("1", "true", "yes")
TOKEN = None


def raw(path, payload=None, headers=None, method=None):
    """Returns (status, headers_dict_lower, body_bytes). Never raises on HTTP status."""
    data = None
    hdrs = {"Content-Type": "application/json"}
    if TOKEN:
        hdrs["Authorization"] = "Bearer " + TOKEN
    if headers:
        hdrs.update(headers)
    if payload is not None:
        data = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
    req = Request(BASE + path, data=data, headers=hdrs, method=method)
    try:
        resp = urlopen(req, timeout=60)
        status = resp.status
        rheaders = dict(resp.headers.items())
        body = resp.read()
    except HTTPError as exc:
        status = exc.code
        rheaders = dict(exc.headers.items()) if exc.headers else {}
        try:
            body = exc.read()
        except Exception:
            body = b""
    return status, {k.lower(): v for k, v in rheaders.items()}, body


def check(name, cond, evidence=""):
    assert cond, f"DAST FAIL [{name}]: {evidence}"
    print(f"DAST PASS [{name}]")


def login(username, password):
    return raw("/api/auth/login", payload={"username": username, "password": password})


# ── 1. Security headers ──────────────────────────────────────────────
status, headers, _ = raw("/api/health")
check("health-200", status == 200, status)
for header, want in [
    ("x-content-type-options", "nosniff"),
    ("referrer-policy", "no-referrer"),
    ("cache-control", "no-store"),
    ("x-frame-options", "DENY"),
    ("strict-transport-security", "max-age=31536000"),
]:
    check(f"header-{header}", want.lower() in headers.get(header, "").lower(),
          dict(headers))

# ── 2. Backend API docs not reachable on the public surface ────────────
# NOTE: on the composed stack :18080 is nginx; /docs answers 200 with the SPA
# fallback, never the backend. So this asserts absence of Swagger/OpenAPI
# markers, not a 404 — a 404 from a tighter nginx config passes just as well.
if EXPECT_PROD:
    _, _, docs_body = raw("/docs")
    lowered = docs_body.lower()
    check("docs-no-swagger", b"swagger-ui" not in lowered and b"redoc" not in lowered,
          docs_body[:150])
    _, _, schema_body = raw("/openapi.json")
    check("docs-no-openapi", b'"openapi"' not in schema_body, schema_body[:150])
else:
    print("DAST SKIP [docs-no-swagger]: dev stack keeps backend docs enabled")

# ── 3. Auth boundary ─────────────────────────────────────────────────
saved = TOKEN
TOKEN = None
for path in ("/api/auth/me", "/api/desk/heston/price", "/api/ml/experiments"):
    status, _, _ = raw(path, method="GET" if path != "/api/desk/heston/price" else "POST")
    check(f"auth401:{path}", status == 401, status)
TOKEN = "garbage-token-that-signs-nothing"
status, _, _ = raw("/api/auth/me")
check("auth401:garbage-token", status == 401, status)
TOKEN = saved

# ── 4. Real login ────────────────────────────────────────────────────
# First, because probe 10 exhausts the shared 10/minute IP bucket on purpose
# and nothing after it may need /login.
status, login_headers, login_body = login(USER, PASSWORD)
check("login-200", status == 200, (status, login_body[:200]))
TOKEN = json.loads(login_body)["access_token"]

# ── 5. No stack traces in error bodies ───────────────────────────────
# (The malformed-JSON POST below consumes 1 request of the /login IP budget.)
status, _, body = raw("/api/route-that-does-not-exist")
check("404-json", status == 404 and b"Traceback" not in body, (status, body[:200]))
status, _, body = raw(
    "/api/auth/login", payload=b'{"username": "x", broken json',
    headers={"Content-Type": "application/json"},
)
check("400-malformed-no-traceback", status in (400, 422) and b"Traceback" not in body,
      (status, body[:200]))
status, _, body = raw("/api/desk/heston/calibrate", payload={"S0": -5, "quotes": []})
check("422-validation-no-traceback", status in (400, 422) and b"Traceback" not in body,
      (status, body[:200]))

# ── 6. Oversize body → fast 413 ──────────────────────────────────────
big = b'{"pad": "' + b"x" * (6 * 1024 * 1024) + b'"}'
started = time.monotonic()
status, _, body = raw("/api/auth/login", payload=big)
elapsed = time.monotonic() - started
check("oversize-413", status == 413, (status, body[:120]))
check("oversize-fast", elapsed < 10, f"{elapsed:.1f}s")

# ── 7. CORS never reflects a foreign origin ──────────────────────────
status, headers, _ = raw("/api/health", headers={"Origin": "https://evil.test"})
reflected = headers.get("access-control-allow-origin", "")
check("cors-no-reflect", reflected != "https://evil.test",
      f"reflected evil origin (status {status})")
if reflected not in ("", "null"):
    check("cors-no-evil-credentials",
          headers.get("access-control-allow-credentials", "").lower() != "true",
          dict(headers))

# ── 8. Health leaks no key material ──────────────────────────────────
status, _, body = raw("/api/health")
health = json.loads(body)
ai_conf = health.get("ai_configuration", {})
check("health-ai-booleans",
      isinstance(ai_conf, dict) and ai_conf and all(v in (True, False) for v in ai_conf.values()),
      ai_conf)
blob = json.dumps(health)
for needle in ("sk-", "AKIA", "BEGIN ", "Bearer "):
    check(f"health-no-{needle.strip().lower()}", needle not in blob, blob[:300])

# ── 9. Refresh cookie flags ──────────────────────────────────────────
set_cookie = login_headers.get("set-cookie", "")
check("cookie-httponly", "httponly" in set_cookie.lower(), set_cookie[:200])
check("cookie-samesite", "samesite=lax" in set_cookie.lower(), set_cookie[:200])
if EXPECT_PROD:
    check("cookie-secure", "secure" in set_cookie.lower(), set_cookie[:200])
else:
    print("DAST SKIP [cookie-secure]: dev mode does not set Secure")

# ── 10. Login rate limit (brute-force backstop) — LAST ─────────────────
# Deliberately burns the 10/minute IP bucket: real login + malformed + oversize
# above consumed 3, so the 429 must land within a few attempts; 30 tolerates a
# minute-boundary rollover mid-probe. Nothing after this uses /login.
seen_429 = False
for _ in range(30):
    status, _, _ = raw("/api/auth/login",
                        payload={"username": "dast-nonexistent-user",
                                 "password": "WrongPassword123!"},
                        headers={"Authorization": ""})
    if status == 429:
        seen_429 = True
        break
    assert status == 401, f"DAST FAIL [login-probe]: expected 401/429, got {status}"
check("login-rate-limited", seen_429, "no 429 in 30 bad logins (10/minute limit?)")

print(json.dumps({"dast": "passed", "production_mode": EXPECT_PROD}))
