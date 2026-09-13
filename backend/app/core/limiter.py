from slowapi import Limiter
from slowapi.util import get_remote_address
from starlette.requests import Request


def rate_limit_key(request: Request) -> str:
    """Prefer the JWT subject so many users behind nginx do not share one IP bucket."""
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        token = auth[7:].strip()
        if token:
            from app.core.security import decode_token
            username = decode_token(token)
            if username:
                return f"user:{username}"
    return get_remote_address(request)


limiter = Limiter(key_func=rate_limit_key, default_limits=["200/minute"])
