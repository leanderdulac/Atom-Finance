"""OKX / Hyperliquid public perp feeds — recorded fixtures, no network in CI."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from unittest.mock import MagicMock

import httpx
import pytest

from app.models.stat_arb_paper import (
    PairBar,
    PaperBook,
    PipelineConfig,
    accrue_funding,
    run_paper_pipeline,
    synthetic_perp_pair,
)
from app.services.perp_feeds import (
    attach_funding,
    fetch_okx_mark_candles,
    fetch_perp_candles,
    parse_hyperliquid_candles,
    parse_hyperliquid_funding,
    parse_okx_funding_current,
    parse_okx_funding_history,
    parse_okx_mark_candles,
    to_hyperliquid_coin,
    to_okx_inst_id,
    to_utc_ms,
)
from app.services.perp_klines import fetch_eth_sol_pair, fetch_mark_klines

FIXTURES = Path(__file__).parent / "fixtures" / "perp_feeds"

T0 = 1_700_000_000_000
H = 3_600_000


def _load(name: str):
    return json.loads((FIXTURES / name).read_text())


def _resp(payload, status=200):
    r = MagicMock()
    r.status_code = status
    if status >= 400:
        request = httpx.Request("GET", "https://example.test")
        r.raise_for_status.side_effect = httpx.HTTPStatusError(
            "error", request=request, response=httpx.Response(status, request=request),
        )
    else:
        r.raise_for_status = MagicMock()
    r.json.return_value = payload
    return r


class TestSymbolsAndTimestamps:
    def test_symbol_maps(self):
        assert to_okx_inst_id("ETHUSDT") == "ETH-USDT-SWAP"
        assert to_okx_inst_id("eth-usdt") == "ETH-USDT-SWAP"
        assert to_okx_inst_id("ETH-USDT-SWAP") == "ETH-USDT-SWAP"
        assert to_hyperliquid_coin("ETHUSDT") == "ETH"
        assert to_hyperliquid_coin("SOL-USDT") == "SOL"

    def test_timestamp_normalization(self):
        assert to_utc_ms(1_700_000_000) == T0
        assert to_utc_ms(T0) == T0
        assert to_utc_ms("1700000000000") == T0
        assert to_utc_ms("not-a-ts") is None
        assert to_utc_ms(-1) is None


class TestParsers:
    def test_okx_mark_newest_first_becomes_chronological_ohlc(self):
        candles = parse_okx_mark_candles(_load("okx_mark_page1.json"))
        assert [c.ts_ms for c in candles] == [T0 + 2 * H, T0 + 3 * H]
        assert candles[0].open == 2002.0
        assert candles[0].close == 2003.0
        assert candles[1].high == 2004.0
        assert candles[0].funding_rate == 0.0

    def test_okx_empty_and_error_are_empty_lists(self, caplog):
        caplog.set_level("WARNING")
        assert parse_okx_mark_candles(_load("okx_mark_empty.json")) == []
        assert parse_okx_mark_candles(_load("okx_mark_error.json")) == []
        assert parse_okx_mark_candles(None) == []
        assert any("empty/error" in r.message or "no rows" in r.message for r in caplog.records)

    def test_okx_skips_non_finite_row(self, caplog):
        caplog.set_level("WARNING")
        payload = {"code": "0", "data": [["1700000000000", "1", "1", "1", "nan"]]}
        assert parse_okx_mark_candles(payload) == []
        assert any("non-finite" in r.message for r in caplog.records)

    def test_okx_funding_history_sorted(self):
        events = parse_okx_funding_history(_load("okx_funding_history.json"))
        assert events == [(T0, 0.0008), (T0 + 8 * H, 0.0008)]

    def test_okx_funding_current(self):
        events = parse_okx_funding_current(_load("okx_funding_current.json"))
        assert events == [(T0, 0.0001)]

    def test_hl_candles_and_seconds_timestamp(self):
        candles = parse_hyperliquid_candles(_load("hl_candles.json"))
        assert len(candles) == 4
        assert candles[0].ts_ms == T0
        assert candles[0].close == 2001.0
        seconds = parse_hyperliquid_candles(_load("hl_candles_seconds.json"))
        assert seconds[0].ts_ms == T0

    def test_hl_empty_and_error_object(self, caplog):
        caplog.set_level("WARNING")
        assert parse_hyperliquid_candles(_load("hl_candles_empty.json")) == []
        assert parse_hyperliquid_candles(_load("hl_error_object.json")) == []
        assert parse_hyperliquid_candles(None) == []
        assert parse_hyperliquid_funding([]) == []

    def test_hl_funding_sorted(self):
        events = parse_hyperliquid_funding(_load("hl_funding.json"))
        assert events[0] == (T0 + 2, 0.0000125)
        assert events[-1][1] == 0.00001


class TestFundingAttach:
    def test_okx_8h_rate_is_prorated_onto_1h_bars(self):
        candles = parse_okx_mark_candles(_load("okx_mark_page1.json")) + parse_okx_mark_candles(
            _load("okx_mark_page2.json")
        )
        candles = sorted(candles, key=lambda c: c.ts_ms)
        events = parse_okx_funding_history(_load("okx_funding_history.json"))
        out = attach_funding(candles, events, interval_ms=H, default_period_ms=8 * H)
        assert out
        # 0.0008 * (1h / 8h) = 0.0001
        assert out[0].funding_rate == pytest.approx(0.0001)
        assert out[-1].funding_rate == pytest.approx(0.0001)

    def test_hl_hourly_rate_lands_on_matching_bar(self):
        candles = parse_hyperliquid_candles(_load("hl_candles.json"))
        events = parse_hyperliquid_funding(_load("hl_funding.json"))
        out = attach_funding(candles, events, interval_ms=H, default_period_ms=H)
        assert out[0].funding_rate == pytest.approx(0.0000125)
        assert out[2].funding_rate == pytest.approx(0.00001)

    def test_missing_funding_stays_zero(self):
        candles = parse_hyperliquid_candles(_load("hl_candles.json"))
        out = attach_funding(candles, [], interval_ms=H, default_period_ms=H)
        assert all(c.funding_rate == 0.0 for c in out)


class TestOkxPagination:
    @pytest.mark.asyncio
    async def test_pages_are_concatenated_oldest_first(self):
        page1 = _load("okx_mark_page1.json")
        page2 = _load("okx_mark_page2.json")

        async def _get(url, params=None, timeout=None, headers=None):
            after = (params or {}).get("after")
            if after is None:
                return _resp(page1)
            if after == "1700007200000":
                return _resp(page2)
            return _resp({"code": "0", "data": []})

        client = MagicMock()
        client.get = _get
        candles = await fetch_okx_mark_candles(
            "ETHUSDT", client=client, interval="1h", limit=4, page_size=2,
        )
        assert [c.ts_ms for c in candles] == [T0, T0 + H, T0 + 2 * H, T0 + 3 * H]
        assert candles[0].close == 2001.0
        assert candles[-1].close == 2003.5

    @pytest.mark.asyncio
    async def test_http_error_returns_empty_and_logs(self, caplog):
        caplog.set_level("WARNING")

        async def _get(url, params=None, timeout=None, headers=None):
            raise httpx.ConnectError("geo-block")

        client = MagicMock()
        client.get = _get
        candles = await fetch_okx_mark_candles("ETHUSDT", client=client, interval="1h", limit=80)
        assert candles == []
        assert any("failed" in r.message for r in caplog.records)


class TestHyperliquidFetch:
    @pytest.mark.asyncio
    async def test_candle_snapshot_and_funding_attached(self):
        async def _post(url, json=None, timeout=None, headers=None):
            kind = (json or {}).get("type")
            if kind == "candleSnapshot":
                return _resp(_load("hl_candles.json"))
            if kind == "fundingHistory":
                return _resp(_load("hl_funding.json"))
            raise AssertionError(json)

        client = MagicMock()
        client.post = _post
        candles = await fetch_perp_candles(
            "hyperliquid", "ETHUSDT", client=client, interval="1h", limit=80,
        )
        assert len(candles) == 4
        assert candles[0].ts_ms == T0
        assert candles[0].funding_rate == pytest.approx(0.0000125)

    @pytest.mark.asyncio
    async def test_empty_snapshot_does_not_raise(self, caplog):
        caplog.set_level("WARNING")

        async def _post(url, json=None, timeout=None, headers=None):
            return _resp([])

        client = MagicMock()
        client.post = _post
        candles = await fetch_perp_candles(
            "hyperliquid", "SOLUSDT", client=client, interval="1h", limit=80,
        )
        assert candles == []


class TestVenueRouter:
    @pytest.mark.asyncio
    async def test_unknown_venue_is_refused_before_http(self):
        client = MagicMock()
        client.get = MagicMock(side_effect=AssertionError("no network"))
        with pytest.raises(ValueError, match="Unsupported venue"):
            await fetch_mark_klines("ETHUSDT", client=client, interval="1h", limit=80, venue="dydx")
        client.get.assert_not_called()

    @pytest.mark.asyncio
    async def test_okx_venue_uses_swap_inst_and_returns_close_rows(self):
        calls: list[tuple[str, dict]] = []

        async def _get(url, params=None, timeout=None, headers=None):
            calls.append((url, dict(params or {})))
            if "history-mark-price-candles" in url:
                # One page of 4 candles so limit=80 does not keep paging.
                p1 = _load("okx_mark_page1.json")
                p2 = _load("okx_mark_page2.json")
                merged = {"code": "0", "data": p1["data"] + p2["data"]}
                return _resp(merged)
            if "funding-rate-history" in url:
                return _resp(_load("okx_funding_history.json"))
            if "funding-rate" in url:
                return _resp(_load("okx_funding_current.json"))
            raise AssertionError(url)

        client = MagicMock()
        client.get = _get
        rows = await fetch_mark_klines(
            "ETHUSDT", client=client, interval="1h", limit=80, venue="okx",
        )
        assert rows[0] == (T0, 2001.0)
        assert any("history-mark-price-candles" in url for url, _ in calls)
        assert any(p.get("instId") == "ETH-USDT-SWAP" for _, p in calls)
        assert all("fapi.binance.com" not in url for url, _ in calls)

    @pytest.mark.asyncio
    async def test_pair_fetch_carries_venue_and_funding(self):
        async def _get(url, params=None, timeout=None, headers=None):
            p1 = _load("okx_mark_page1.json")
            p2 = _load("okx_mark_page2.json")
            # Repeat the 4-bar page until we have ≥80 aligned stamps for the pair gate.
            base = list(reversed(p1["data"] + p2["data"]))  # chronological
            rows = []
            for i in range(90):
                src = base[i % 4]
                ts = T0 + i * H
                rows.append([str(ts), src[1], src[2], src[3], src[4], "1"])
            rows.reverse()  # OKX newest-first
            if "history-mark-price-candles" in url:
                return _resp({"code": "0", "data": rows})
            if "funding-rate-history" in url:
                return _resp(_load("okx_funding_history.json"))
            return _resp(_load("okx_funding_current.json"))

        client = MagicMock()
        client.get = _get
        pulled = await fetch_eth_sol_pair(client=client, interval="1h", limit=90, venue="okx")
        assert pulled["signed"] is False
        assert pulled["broker_orders_sent"] == 0
        assert pulled["venue"] == "okx"
        assert pulled["source"] == "okx_swap_mark_candles"
        assert len(pulled["bars"]) >= 80
        assert pulled["bars"][0].y_funding == pytest.approx(0.0001)


class TestFundingPnl:
    def test_longs_pay_positive_funding(self):
        book = PaperBook(cash=10_000.0, y_qty=1.0, x_qty=-2.0, shadow_cash=10_000.0)
        bar = PairBar(1, 2000.0, 100.0, 1999.0, 2001.0, 99.9, 100.1, y_funding=0.0001, x_funding=0.0002)
        delta = accrue_funding(book, bar)
        assert delta == pytest.approx(-0.16)
        assert book.funding_pnl == pytest.approx(-0.16)
        assert book.cash == pytest.approx(9_999.84)
        assert book.shadow_cash == pytest.approx(9_999.84)

    def test_flat_book_accrues_nothing(self):
        book = PaperBook(cash=10_000.0, shadow_cash=10_000.0)
        bar = PairBar(1, 2000.0, 100.0, 1999.0, 2001.0, 99.9, 100.1, y_funding=0.01, x_funding=0.01)
        assert accrue_funding(book, bar) == 0.0
        assert book.funding_pnl == 0.0

    def test_pipeline_reports_funding_separately_from_price_pnl(self):
        bars = synthetic_perp_pair(n=400, seed=11, half_life=8.0, resid_vol=3.5)
        funded = [replace(b, y_funding=0.0001, x_funding=0.00005) for b in bars]
        out = run_paper_pipeline(
            funded,
            PipelineConfig(entry_z=1.5, exit_z=0.4, taker_fee_bps=4.0, half_spread_bps=2.0),
            source="synthetic",
        )
        assert out["eligible_for_live_trading"] is False
        assert out["accepted"] is True
        net = out["monitoring"]["pnl_net"]
        price = out["monitoring"]["pnl_price"]
        funding = out["monitoring"]["pnl_funding"]
        costs = out["execution"]["costs_paid"]
        assert funding != 0.0
        assert net == pytest.approx(price + funding, abs=1e-3)
        assert net == pytest.approx(out["monitoring"]["pnl_gross"] - costs, abs=1e-3)
        assert out["execution"]["funding_applied"] == pytest.approx(funding)
        assert out["broker_orders_sent"] == 0
