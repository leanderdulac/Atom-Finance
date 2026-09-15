"""Rate-limit key behaviour — brute-force protection behind nginx."""

from starlette.requests import Request

from app.core.limiter import _client_ip, rate_limit_key


def _make_request(headers=None, client=("10.0.0.9", 4000)):
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/",
        "headers": [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()],
        "client": client,
        "scheme": "http",
        "server": ("test", 80),
    }
    return Request(scope)


def test_bearer_token_keys_on_user(monkeypatch):
    from app.core import security
    req = _make_request({"Authorization": f"Bearer {security.create_access_token('alice')}"})
    assert rate_limit_key(req) == "user:alice"


def test_no_trust_uses_peer_ip(monkeypatch):
    monkeypatch.delenv("ATOM_TRUST_X_FORWARDED_FOR", raising=False)
    # A spoofed X-Forwarded-For must be IGNORED when the operator has not opted in.
    req = _make_request({"X-Forwarded-For": "1.2.3.4, 5.6.7.8"}, client=("192.168.1.50", 5000))
    assert rate_limit_key(req) == "ip:192.168.1.50"


def test_trusted_proxy_keys_on_first_xff(monkeypatch):
    monkeypatch.setenv("ATOM_TRUST_X_FORWARDED_FOR", "1")
    req = _make_request({"X-Forwarded-For": "203.0.113.42, 192.168.1.50"}, client=("192.168.1.50", 5000))
    # leftmost is the real client as appended by nginx
    assert rate_limit_key(req) == "ip:203.0.113.42"


def test_trusted_proxy_falls_back_when_no_xff(monkeypatch):
    monkeypatch.setenv("ATOM_TRUST_X_FORWARDED_FOR", "1")
    req = _make_request(client=("192.168.1.50", 5000))
    assert rate_limit_key(req) == "ip:192.168.1.50"


def test_client_ip_direct_without_trust(monkeypatch):
    monkeypatch.delenv("ATOM_TRUST_X_FORWARDED_FOR", raising=False)
    req = _make_request(client=("10.1.1.7", 4444))
    assert _client_ip(req) == "10.1.1.7"
