#!/usr/bin/env python3
"""Same-origin static + /api proxy for the Mac public UI.

Serves `dist/` (SPA fallback) and forwards `/api` to the FastAPI process so a
single Cloudflare tunnel to ATOM_UI_PORT is enough. Binds 127.0.0.1 by default.
Stdlib only — no Node, no Caddy.
"""
from __future__ import annotations

import os
import sys
from http.server import ThreadingHTTPServer
from pathlib import Path

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

from serve_lib import load_env_file, make_handler  # noqa: E402


def _env_file() -> Path | None:
    raw = os.environ.get("ATOM_ENV_FILE", "").strip()
    if raw:
        return Path(raw)
    home = os.environ.get("ATOM_HOME", "").strip()
    if home:
        return Path(home) / ".env"
    return _HERE.parents[1] / ".env"


def main() -> int:
    env_path = _env_file()
    if env_path and env_path.is_file():
        load_env_file(env_path)

    home = Path(os.environ.get("ATOM_HOME") or _HERE.parents[1])
    dist = Path(os.environ.get("ATOM_DIST") or home / "dist")
    ui_host = os.environ.get("ATOM_UI_HOST", "127.0.0.1").strip() or "127.0.0.1"
    ui_port = int(os.environ.get("ATOM_UI_PORT", "4173") or "4173")
    api_host = os.environ.get("ATOM_API_HOST", "127.0.0.1").strip() or "127.0.0.1"
    api_port = int(os.environ.get("ATOM_API_PORT", "8000") or "8000")

    if not dist.is_dir():
        print(f"dist/ não encontrado em {dist}. Rode npm run build.", file=sys.stderr)
        return 1

    handler = make_handler(dist, api_host, api_port)
    httpd = ThreadingHTTPServer((ui_host, ui_port), handler)
    print(
        f"ATOM UI {ui_host}:{ui_port} → dist={dist} api={api_host}:{api_port}",
        flush=True,
    )
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("ATOM UI stopped", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
