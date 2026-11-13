"""Pytest configuration for ATOM backend tests."""
import os

import pytest
import pytest_asyncio

# Must be set before any app imports so security.py takes the dev/test path
os.environ.setdefault("ATOM_ENV", "test")
# Use a fixed secret key in tests so JWT tokens are deterministic
os.environ.setdefault("SECRET_KEY", "test-secret-key-do-not-use-in-production")
# Point to a non-existent Redis so tests always use in-memory cache
os.environ.setdefault("REDIS_URL", "redis://localhost:19999/0")
# Local dev/CI Postgres — see CONTRIBUTING.md for how to run one locally.
os.environ.setdefault("ATOM_DATABASE_URL", "postgresql+asyncpg://atom:atom_dev@localhost:5432/atom_test")
# Client assembler must not block tests on a local Ollama that is not there.
os.environ.setdefault("OLLAMA_ENABLED", "0")
os.environ.setdefault("ATOM_CLIENT_MODE", "false")
os.environ.setdefault("ATOM_CLIENT_JOB", "0")
os.environ.setdefault("ATOM_CONTEXT_JOB", "0")
os.environ.setdefault("ATOM_WORKER_CONTEXT", "0")
os.environ.setdefault("ATOM_AGENT_LLM", "ollama")
os.environ.setdefault("SEARXNG_URL", "")
os.environ.setdefault("BRAVE_API_KEY", "")
os.environ.setdefault("TAVILY_API_KEY", "")
# Unit tests never see a real xAI/OpenAI key. Live markers restore them.
_XAI_KEY_FROM_ENV = os.environ.get("XAI_API_KEY", "")
_OPENAI_KEY_FROM_ENV = os.environ.get("OPENAI_API_KEY", "")
os.environ["XAI_API_KEY"] = ""
os.environ["OPENAI_API_KEY"] = ""
os.environ.setdefault("ATOM_XAI_LIVE", "0")
os.environ.setdefault("ATOM_OPENAI_LIVE", "0")
os.environ.setdefault("ATOM_RISK_PROVIDER", "ollama")

@pytest.fixture(autouse=True)
def _xai_key_for_live_marker(monkeypatch, request):
    """Blank xAI in unit tests; restore only for @pytest.mark.xai."""
    if request.node.get_closest_marker("xai"):
        monkeypatch.setenv("XAI_API_KEY", _XAI_KEY_FROM_ENV)
    else:
        monkeypatch.setenv("XAI_API_KEY", "")
    yield


@pytest.fixture(autouse=True)
def _openai_key_for_live_marker(monkeypatch, request):
    """Blank OpenAI in unit tests; restore only for @pytest.mark.openai."""
    if request.node.get_closest_marker("openai"):
        monkeypatch.setenv("OPENAI_API_KEY", _OPENAI_KEY_FROM_ENV)
    else:
        monkeypatch.setenv("OPENAI_API_KEY", "")
    yield


@pytest.fixture(autouse=True)
def _silence_context_http(monkeypatch, request):
    """Unit tests never hit SearXNG/Brave/exchanges. Live Ollama tests opt out."""
    if (
        request.node.get_closest_marker("ollama")
        or request.node.get_closest_marker("xai")
        or request.node.get_closest_marker("openai")
    ):
        yield
        return

    def _none(*_a, **_k):
        return None

    import importlib

    for mod_name in (
        "app.services.context.http",
        "app.services.context.search",
        "app.services.context.rss",
        "app.services.context.calendar",
        "app.services.context.crypto",
    ):
        mod = importlib.import_module(mod_name)
        for attr in ("cached_get_json", "cached_get_text", "cached_post_json"):
            if hasattr(mod, attr):
                monkeypatch.setattr(mod, attr, _none)
    yield


def _redacted_database_url() -> str:
    """Connection target without the password — this string reaches CI logs."""
    from urllib.parse import urlsplit, urlunsplit

    from app.db.postgres import _database_url

    parts = urlsplit(_database_url())
    if parts.password is None:
        return parts.geturl()
    host = parts.hostname or ""
    if parts.port:
        host = f"{host}:{parts.port}"
    return urlunsplit(parts._replace(netloc=f"{parts.username}:***@{host}"))


_TABLES = (
    "reports", "users", "experiments", "experiment_reviews",
    "derivative_plans", "source_snapshots", "paper_trades", "paper_events",
    "sentiment_snapshots",
)


@pytest_asyncio.fixture(autouse=True)
async def _clean_db():
    """Every test starts from an empty database — tests share one real
    Postgres instance now (no more per-test SQLite file via monkeypatching
    ATOM_DB_PATH), so isolation comes from truncating between tests instead.

    Truncates over a standalone connection, not the app's shared pool: a
    sync test using `TestClient(app)` drives the ASGI app on its own
    internally-managed event loop, separate from this (async) fixture's
    loop. asyncpg pools are bound to the loop that created them, so if this
    fixture created the shared pool here, the app's first DB call from
    TestClient's loop would crash with "attached to a different loop".
    close_pool() at teardown still resets the *app's* pool (if the test
    caused one to be created) so the next test — quite possibly running on
    yet another fresh event loop — doesn't inherit a pool bound to a loop
    that no longer exists.
    """
    if os.getenv("ATOM_SKIP_DB") == "1":
        yield
        return

    import asyncpg

    from app.db.postgres import _database_url, close_pool

    try:
        conn = await asyncpg.connect(_database_url())
    except (OSError, asyncpg.PostgresError) as exc:
        # Without this, an absent Postgres surfaces as one connection traceback
        # per test — hundreds of them — none of which says what to start.
        pytest.exit(
            f"Cannot reach the test database at {_redacted_database_url()}\n"
            f"  {type(exc).__name__}: {exc}\n\n"
            "Start a local Postgres and create atom_test (see CONTRIBUTING.md), "
            "override ATOM_DATABASE_URL, or set ATOM_SKIP_DB=1 to run only the "
            "tests that do not touch the database.",
            returncode=pytest.ExitCode.USAGE_ERROR,
        )
    try:
        await conn.execute(f"TRUNCATE {', '.join(_TABLES)} RESTART IDENTITY CASCADE")
    finally:
        await conn.close()
    yield
    await close_pool()
