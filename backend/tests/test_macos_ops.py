"""ops/macos: SECRET_KEY, venv path, quick-tunnel URL, same-origin /api proxy."""
from __future__ import annotations

import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
MACOS = REPO / "ops" / "macos"
sys.path.insert(0, str(MACOS))

from ensure_secret import apply, current_secret, ensure, needs_secret  # noqa: E402
from serve_lib import is_api_path, make_handler, safe_dist_file  # noqa: E402


def test_needs_secret_treats_placeholder_as_missing():
    assert needs_secret(None)
    assert needs_secret("")
    assert needs_secret("REPLACE_WITH_GENERATED_KEY")
    assert not needs_secret("a" * 64)


def test_ensure_secret_generates_without_printing(tmp_path, capsys):
    env = tmp_path / ".env"
    env.write_text("ATOM_DATABASE_URL=postgresql://x\nSECRET_KEY=\n", encoding="utf-8")
    assert ensure(env) == "generated"
    value = current_secret(env.read_text(encoding="utf-8"))
    assert value is not None and len(value) == 64 and all(c in "0123456789abcdef" for c in value)
    captured = capsys.readouterr()
    assert value not in captured.out
    assert value not in captured.err
    assert ensure(env) == "kept"
    assert current_secret(env.read_text(encoding="utf-8")) == value


def test_ensure_secret_cli_is_silent_about_the_key(tmp_path):
    env = tmp_path / ".env"
    env.write_text("ATOM_CLIENT_MODE=true\n", encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, str(MACOS / "ensure_secret.py"), str(env)],
        check=True,
        capture_output=True,
        text=True,
    )
    key = current_secret(env.read_text(encoding="utf-8"))
    assert key and len(key) == 64
    assert key not in proc.stdout
    assert key not in proc.stderr
    assert "não exibido" in proc.stdout


def test_apply_replaces_placeholder_and_appends_when_missing():
    body = apply("SECRET_KEY=REPLACE_WITH_GENERATED_KEY\nFOO=1\n", "deadbeef")
    assert "SECRET_KEY=deadbeef\n" in body
    assert "REPLACE_WITH_GENERATED_KEY" not in body
    assert apply("FOO=1\n", "abc").endswith("SECRET_KEY=abc\n")


def test_lib_sh_venv_and_trycloudflare_url():
    script = r"""
set -euo pipefail
source "$1"
ATOM_VENV=/opt/atom/.venv
printf 'venv=%s\n' "$(atom_resolve_venv /repo)"
unset ATOM_VENV
printf 'default=%s\n' "$(atom_resolve_venv /repo)"
printf 'url=%s\n' "$(atom_extract_trycloudflare_url 'INF |  https://foo-bar.trycloudflare.com')"
printf 'none=%s\n' "$(atom_extract_trycloudflare_url 'no url here')"
"""
    proc = subprocess.run(
        ["bash", "-c", script, "bash", str(MACOS / "lib.sh")],
        check=True,
        capture_output=True,
        text=True,
    )
    assert "venv=/opt/atom/.venv" in proc.stdout
    assert "default=/repo/backend/venv" in proc.stdout
    assert "url=https://foo-bar.trycloudflare.com" in proc.stdout
    assert "none=\n" in proc.stdout or proc.stdout.strip().endswith("none=")


def test_install_and_wrappers_are_valid_bash():
    for name in ("install.sh", "uninstall.sh", "backend.sh", "worker.sh", "tunnel.sh", "lib.sh"):
        subprocess.run(["bash", "-n", str(MACOS / name)], check=True)


def test_plists_bind_via_wrappers_not_0_0_0_0():
    backend = (MACOS / "com.atom.backend.plist.tpl").read_text(encoding="utf-8")
    frontend = (MACOS / "com.atom.frontend.plist.tpl").read_text(encoding="utf-8")
    tunnel = (MACOS / "com.atom.tunnel.plist.tpl").read_text(encoding="utf-8")
    assert "0.0.0.0" not in backend
    assert "backend.sh" in backend
    assert "serve.py" in frontend
    assert "tunnel.sh" in tunnel
    assert "CLOUDFLARE_TUNNEL_TOKEN" not in tunnel  # token stays in .env


def test_is_api_and_safe_dist(tmp_path):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "atom.svg").write_text("<svg/>", encoding="utf-8")
    nested = dist / "assets"
    nested.mkdir()
    (nested / "app.js").write_text("ok", encoding="utf-8")
    assert is_api_path("/api")
    assert is_api_path("/api/client/config")
    assert not is_api_path("/cliente")
    assert not is_api_path("/apiary")
    assert safe_dist_file(dist, "/atom.svg").name == "atom.svg"
    assert safe_dist_file(dist, "/assets/app.js").name == "app.js"
    assert safe_dist_file(dist, "/cliente") is None
    assert safe_dist_file(dist, "/../atom.svg") is None or safe_dist_file(dist, "/../atom.svg") == dist / "atom.svg"


class _Api(BaseHTTPRequestHandler):
    def log_message(self, *args) -> None:  # noqa: A003
        return

    def do_GET(self) -> None:  # noqa: N802
        body = b'{"status":"healthy"}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:  # noqa: N802
        n = int(self.headers.get("Content-Length") or 0)
        payload = self.rfile.read(n)
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


@pytest.fixture
def ui_and_api(tmp_path):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<!doctype html><title>ATOM</title>spa", encoding="utf-8")
    (dist / "atom.svg").write_text("<svg id='logo'/>", encoding="utf-8")

    api = ThreadingHTTPServer(("127.0.0.1", 0), _Api)
    ui = ThreadingHTTPServer(
        ("127.0.0.1", 0),
        make_handler(dist, "127.0.0.1", api.server_address[1]),
    )
    threads = [
        threading.Thread(target=api.serve_forever, daemon=True),
        threading.Thread(target=ui.serve_forever, daemon=True),
    ]
    for t in threads:
        t.start()
    yield ui, api
    ui.shutdown()
    api.shutdown()


def test_ui_serves_spa_and_proxies_api(ui_and_api):
    import urllib.request

    ui, _api = ui_and_api
    origin = f"http://127.0.0.1:{ui.server_address[1]}"

    with urllib.request.urlopen(origin + "/") as res:
        assert b"spa" in res.read()
        assert res.headers.get_content_type() == "text/html"
    with urllib.request.urlopen(origin + "/cliente") as res:
        assert b"spa" in res.read()
    with urllib.request.urlopen(origin + "/atom.svg") as res:
        assert b"logo" in res.read()
    with urllib.request.urlopen(origin + "/api/health") as res:
        assert b"healthy" in res.read()

    req = urllib.request.Request(
        origin + "/api/client/ready-operation",
        data=b'{"ticker":"PETR4"}',
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req) as res:
        assert res.read() == b'{"ticker":"PETR4"}'

    with urllib.request.urlopen(origin + "/does-not-exist") as res:
        assert res.status == 200
        assert b"spa" in res.read()


def test_backend_sh_uses_env_port_not_all_interfaces():
    text = (MACOS / "backend.sh").read_text(encoding="utf-8")
    assert "ATOM_API_HOST:-127.0.0.1" in text
    assert "0.0.0.0" not in text
    assert "caffeinate" in text
