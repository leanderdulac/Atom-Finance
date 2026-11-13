"""Pure helpers for the Mac UI server — imported by serve.py and by tests."""
from __future__ import annotations

import mimetypes
import posixpath
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import unquote, urlsplit

HOP_BY_HOP = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
}

_MIME_FALLBACK = {
    ".js": "application/javascript",
    ".mjs": "application/javascript",
    ".css": "text/css",
    ".svg": "image/svg+xml",
    ".json": "application/json",
    ".map": "application/json",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
    ".html": "text/html; charset=utf-8",
}


def load_env_file(path: Path) -> None:
    """Fill os.environ with KEY=VALUE from path when the key is not already set."""
    import os

    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        if key and key not in os.environ:
            os.environ[key] = value


def is_api_path(path: str) -> bool:
    return path == "/api" or path.startswith("/api/")


def safe_dist_file(dist: Path, url_path: str) -> Path | None:
    """Return a file under dist for this URL, or None (caller serves index.html)."""
    parsed = urlsplit(url_path)
    rel = unquote(parsed.path)
    rel = posixpath.normpath("/" + rel.lstrip("/")).lstrip("/")
    if rel in {"", "."}:
        return None
    candidate = (dist / rel).resolve()
    try:
        candidate.relative_to(dist.resolve())
    except ValueError:
        return None
    if candidate.is_file():
        return candidate
    return None


def content_type(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in _MIME_FALLBACK:
        return _MIME_FALLBACK[suffix]
    guess, _ = mimetypes.guess_type(str(path))
    return guess or "application/octet-stream"


def make_handler(dist: Path, api_host: str, api_port: int, timeout: float = 60.0) -> type[BaseHTTPRequestHandler]:
    dist = dist.resolve()
    index = dist / "index.html"

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args) -> None:  # noqa: A003
            sys_stderr = __import__("sys").stderr
            print(f"[atom-ui] {self.address_string()} {fmt % args}", file=sys_stderr, flush=True)

        def _serve_index(self) -> None:
            data = index.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def _serve_file(self, path: Path) -> None:
            data = path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", content_type(path))
            self.send_header("Content-Length", str(len(data)))
            if path.suffix in {".html"}:
                self.send_header("Cache-Control", "no-store")
            else:
                self.send_header("Cache-Control", "public, max-age=31536000, immutable")
            self.end_headers()
            self.wfile.write(data)

        def _proxy(self) -> None:
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length) if length else None
            conn = HTTPConnection(api_host, api_port, timeout=timeout)
            headers = {
                k: v
                for k, v in self.headers.items()
                if k.lower() not in HOP_BY_HOP and k.lower() != "host"
            }
            headers["Host"] = f"{api_host}:{api_port}"
            headers["X-Forwarded-Host"] = self.headers.get("Host") or ""
            headers["X-Forwarded-Proto"] = "https" if self.headers.get("X-Forwarded-Proto") else "http"
            try:
                conn.request(self.command, self.path, body=body, headers=headers)
                upstream = conn.getresponse()
                payload = upstream.read()
                self.send_response(upstream.status)
                for key, value in upstream.getheaders():
                    if key.lower() in HOP_BY_HOP:
                        continue
                    self.send_header(key, value)
                self.end_headers()
                self.wfile.write(payload)
            except OSError as exc:
                msg = f"API indisponível em {api_host}:{api_port} ({exc.__class__.__name__})".encode()
                self.send_response(502)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.send_header("Content-Length", str(len(msg)))
                self.end_headers()
                self.wfile.write(msg)
            finally:
                conn.close()

        def do_GET(self) -> None:  # noqa: N802
            if is_api_path(urlsplit(self.path).path):
                self._proxy()
                return
            target = safe_dist_file(dist, self.path)
            if target is not None:
                self._serve_file(target)
                return
            if index.is_file():
                self._serve_index()
                return
            self.send_error(404, "dist/index.html ausente")

        def do_HEAD(self) -> None:  # noqa: N802
            self.do_GET()

        def do_POST(self) -> None:  # noqa: N802
            self._proxy() if is_api_path(urlsplit(self.path).path) else self.send_error(404)

        def do_PUT(self) -> None:  # noqa: N802
            self.do_POST()

        def do_PATCH(self) -> None:  # noqa: N802
            self.do_POST()

        def do_DELETE(self) -> None:  # noqa: N802
            self.do_POST()

        def do_OPTIONS(self) -> None:  # noqa: N802
            if is_api_path(urlsplit(self.path).path):
                self._proxy()
                return
            self.send_response(204)
            self.send_header("Allow", "GET, HEAD, OPTIONS")
            self.end_headers()

    return Handler
