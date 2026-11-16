import os

from slowapi import Limiter
from slowapi.util import get_remote_address
from starlette.requests import Request


def _trusted_proxy_hops() -> int:
    """How many trusted proxies sit between the internet and this app.

    Each trusted proxy APPENDS the IP of its own peer to the right end of
    X-Forwarded-For, so the real client is the entry added by the outermost
    trusted proxy: `entries[-hops]`. Anything further left may be client-supplied
    junk ($proxy_add_x_forwarded_for preserves an incoming XFF) and is ignored.
    """
    raw = os.getenv("ATOM_TRUST_PROXY_HOPS", "1").strip()
    try:
        return max(1, int(raw))
    except ValueError:
        return 1


def _client_ip(request: Request) -> str:
    """Real client IP, honouring X-Forwarded-For only when explicitly trusted.

    Behind nginx, `get_remote_address` returns the proxy's IP, so *every*
    unauthenticated attempt (login/register) would share ONE nginx bucket —
    collapsing the brute-force limit to a single global cap. When the operator
    sets ATOM_TRUST_X_FORWARDED_FOR=1 (the deployment runs the backend behind
    its own nginx), the X-Forwarded-For entry added by the outermost trusted
    proxy is used instead — counted from the RIGHT by ATOM_TRUST_PROXY_HOPS
    (1 = nginx only, 2 = Caddy edge + nginx), never the leftmost, which the
    client can seed freely. It defaults to OFF so a backend that is exposed
    directly cannot be bypassed by a client spoofing the header.
    """
    if os.getenv("ATOM_TRUST_X_FORWARDED_FOR", "").strip().lower() in ("1", "true", "yes"):
        xfwd = request.headers.get("X-Forwarded-For", "")
        entries = [e.strip() for e in xfwd.split(",") if e.strip()]
        hops = _trusted_proxy_hops()
        if len(entries) >= hops:
            return entries[-hops]
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

