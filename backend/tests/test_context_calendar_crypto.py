"""Macro calendar fallback and crypto positioning — no invented prints."""
from __future__ import annotations

from datetime import date

from app.services.context import calendar, crypto, gather


def test_calendar_window_uses_fallback(monkeypatch):
    monkeypatch.setattr("app.services.context.calendar.cached_get_json", lambda *a, **k: None)
    rows = calendar.upcoming_events(horizon_days=40, today=date(2026, 11, 10))
    names = {r["nome"] for r in rows}
    assert "CPI (EUA)" in names  # 13 Nov
    assert "FOMC" in names  # 9 Dec within 40d
    for row in rows:
        assert row["url"].startswith("http")
        assert row["data"] >= "2026-11-10"


def test_calendar_empty_outside_year(monkeypatch):
    monkeypatch.setattr("app.services.context.calendar.cached_get_json", lambda *a, **k: None)
    rows = calendar.upcoming_events(horizon_days=5, today=date(2027, 2, 1))
    # fallback list is 2026-only; payroll/CPI heuristics still apply
    assert all(r["data"] >= "2027-02-01" for r in rows)


def test_crypto_none_when_exchanges_down(monkeypatch):
    monkeypatch.setattr("app.services.context.crypto.cached_get_json", lambda *a, **k: None)
    assert crypto.positioning("BTC") is None
    assert crypto.positioning("PETR4") is None


def test_crypto_parses_binance(monkeypatch):
    def fake(url, **kwargs):
        if "premiumIndex" in url:
            return {"lastFundingRate": "0.0001"}
        if "openInterest" in url:
            return {"openInterest": "12345"}
        if "okx.com" in url:
            return {"data": [{"fundingRate": "0.0002"}]}
        if "mempool" in url:
            return {"fastestFee": 4}
        return None

    monkeypatch.setattr("app.services.context.crypto.cached_get_json", fake)
    pos = crypto.positioning("BTC")
    assert pos is not None
    assert pos["binance_funding"] == 0.0001
    assert pos["binance_open_interest"] == 12345.0
    assert pos["okx_funding"] == 0.0002
    assert pos["onchain"]["fonte"].startswith("https://mempool.space")


def test_gather_empty_sources_when_http_dead(monkeypatch):
    monkeypatch.setattr("app.services.context.search.search_news", lambda *a, **k: [])
    monkeypatch.setattr("app.services.context.rss.fetch_rss", lambda *a, **k: [])
    monkeypatch.setattr("app.services.context.calendar.upcoming_events", lambda **k: [])
    monkeypatch.setattr("app.services.context.crypto.positioning", lambda *a, **k: None)
    from app.core.cache import Cache
    Cache.delete("ctx:bundle:PETR4:weeks:equity_br")
    bundle = gather.gather_context("PETR4", "weeks", asset_class="equity_br")
    assert bundle["fontes"] == []
