import os

from slowapi import Limiter
from slowapi.util import get_remote_address
from starlette.requests import Request


def _trusted_hops() -> int:
    """Number of reverse proxies in front of the backend that APPEND to X-Forwarded-For.

    ATOM_TRUST_X_FORWARDED_FOR:
      unset/0/false → ignore the header (backend exposed directly)
      1/true/yes    → one proxy (the frontend nginx)
      N             → N chained proxies (e.g. 2 = Caddy edge → nginx)
    """
    raw = os.getenv("ATOM_TRUST_X_FORWARDED_FOR", "").strip().lower()
    if raw in ("1", "true", "yes"):
        return 1
    try:
        return max(0, int(raw))
    except ValueError:
        return 0


def _client_ip(request: Request) -> str:
    """Real client IP, honouring X-Forwarded-For only for explicitly trusted hops.

    Behind nginx, `get_remote_address` returns the proxy's IP, so *every*
    unauthenticated attempt (login/register) would share ONE nginx bucket —
    collapsing the brute-force limit to a single global cap.

    nginx's `$proxy_add_x_forwarded_for` APPENDS the peer it saw to whatever the
    client sent, so the LEFTMOST entries are attacker-controlled: keying on them
    lets a brute-forcer rotate a fake X-Forwarded-For per request and never hit
    the limit. Only the entries added by our own proxies are trustworthy, i.e.
    the N rightmost ones; the client is the Nth entry from the right.
    """
    hops = _trusted_hops()
    if hops:
        parts = [p.strip() for p in request.headers.get("X-Forwarded-For", "").split(",") if p.strip()]
        if len(parts) >= hops:
            return parts[-hops]
    return get_remote_address(request)


def rate_limit_key(request: Request) -> str:
    """Prefer the JWT subject so authenticated users never share one IP bucket.

    For unauthenticated routes (login/register) there is no token, so fall back to
    the client IP — which is the real client when ATOM_TRUST_X_FORWARDED_FOR=1 is
    set behind nginx, restoring per-attacker brute-force limiting.
    """
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        token = auth[7:].strip()
        if token:
            from app.core.security import decode_token
            username = decode_token(token)
            if username:
                return f"user:{username}"
    return f"ip:{_client_ip(request)}"


limiter = Limiter(key_func=rate_limit_key, default_limits=["200/minute"])

