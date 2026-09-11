"""Tests for DataFetcher — mocks the yfinance boundary, exercises our own
caching, error-handling, and concurrent-fetch logic around it."""
import asyncio
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from app.services.data_fetcher import DataFetcher


def _mock_yf_with_ticker(ticker_mock):
    yf = MagicMock()
    yf.Ticker.return_value = ticker_mock
    return yf


class TestGetQuote:
    def test_returns_cached_value_without_hitting_yfinance(self):
        with patch("app.services.data_fetcher.Cache.get", return_value={"ticker": "CACHED", "price": 1}):
            with patch("app.services.data_fetcher._get_yfinance") as get_yf:
                result = DataFetcher.get_quote("CACHED")
                get_yf.assert_not_called()
        assert result == {"ticker": "CACHED", "price": 1}

    def test_fetches_and_caches_on_cache_miss(self):
        ticker = MagicMock()
        ticker.info = {"currentPrice": 123.45, "regularMarketChange": 1.2, "volume": 1000}
        yf = _mock_yf_with_ticker(ticker)

        with patch("app.services.data_fetcher.Cache.get", return_value=None), \
             patch("app.services.data_fetcher.Cache.set") as cache_set, \
             patch("app.services.data_fetcher._get_yfinance", return_value=yf):
            result = DataFetcher.get_quote("aapl", use_cache=True)

        assert result is not None
        assert result["ticker"] == "AAPL"  # symbol is upper-cased
        assert result["price"] == 123.45
        cache_set.assert_called_once()

    def test_falls_back_to_regular_market_price_when_current_price_missing(self):
        ticker = MagicMock()
        ticker.info = {"regularMarketPrice": 99.0}
        yf = _mock_yf_with_ticker(ticker)
        with patch("app.services.data_fetcher.Cache.get", return_value=None), \
             patch("app.services.data_fetcher.Cache.set"), \
             patch("app.services.data_fetcher._get_yfinance", return_value=yf):
            result = DataFetcher.get_quote("NOPRICE")
        assert result["price"] == 99.0

    def test_returns_none_when_yfinance_unavailable(self):
        with patch("app.services.data_fetcher.Cache.get", return_value=None), \
             patch("app.services.data_fetcher._get_yfinance", return_value=None):
            result = DataFetcher.get_quote("ANY")
        assert result is None

    def test_returns_none_and_does_not_raise_on_yfinance_error(self):
        ticker = MagicMock()
        type(ticker).info = property(lambda self: (_ for _ in ()).throw(RuntimeError("network down")))
        yf = _mock_yf_with_ticker(ticker)
        with patch("app.services.data_fetcher.Cache.get", return_value=None), \
             patch("app.services.data_fetcher._get_yfinance", return_value=yf):
            result = DataFetcher.get_quote("BROKEN")
        assert result is None


class TestGetHistoricalData:
    def test_returns_dataframe_from_yfinance(self):
        df = pd.DataFrame({"Close": [1.0, 2.0, 3.0]})
        ticker = MagicMock()
        ticker.history.return_value = df
        yf = _mock_yf_with_ticker(ticker)
        with patch("app.services.data_fetcher._get_yfinance", return_value=yf):
            result = DataFetcher.get_historical_data("PETR4.SA", period="1y", interval="1d")
        ticker.history.assert_called_once_with(period="1y", interval="1d")
        assert result is not None
        assert list(result["Close"]) == [1.0, 2.0, 3.0]

    def test_returns_none_when_yfinance_unavailable(self):
        with patch("app.services.data_fetcher._get_yfinance", return_value=None):
            assert DataFetcher.get_historical_data("X") is None

    def test_returns_none_on_exception(self):
        ticker = MagicMock()
        ticker.history.side_effect = ValueError("bad symbol")
        yf = _mock_yf_with_ticker(ticker)
        with patch("app.services.data_fetcher._get_yfinance", return_value=yf):
            assert DataFetcher.get_historical_data("BAD") is None


class TestGetOptionsChain:
    def test_returns_none_when_no_expirations(self):
        ticker = MagicMock()
        ticker.options = []
        yf = _mock_yf_with_ticker(ticker)
        with patch("app.services.data_fetcher._get_yfinance", return_value=yf):
            assert DataFetcher.get_options_chain("NOEXP") is None

    def test_builds_chain_from_first_expiration_when_requested_one_is_unavailable(self):
        ticker = MagicMock()
        ticker.options = ("2025-01-17", "2025-02-21")
        chain = MagicMock()
        chain.calls = pd.DataFrame([{"strike": 100, "inTheMoney": False}])
        chain.puts = pd.DataFrame([{"strike": 100, "inTheMoney": True}])
        ticker.option_chain.return_value = chain
        yf = _mock_yf_with_ticker(ticker)
        with patch("app.services.data_fetcher._get_yfinance", return_value=yf):
            result = DataFetcher.get_options_chain("PETR4.SA", expiry_date="not-a-real-date")
        ticker.option_chain.assert_called_once_with("2025-01-17")
        assert result["expiry"] == "2025-01-17"
        assert result["calls"] == [{"strike": 100, "inTheMoney": False}]

    def test_returns_none_on_exception(self):
        ticker = MagicMock()
        ticker.options = ("2025-01-17",)
        ticker.option_chain.side_effect = RuntimeError("boom")
        yf = _mock_yf_with_ticker(ticker)
        with patch("app.services.data_fetcher._get_yfinance", return_value=yf):
            assert DataFetcher.get_options_chain("X") is None


class TestGetVolatilityData:
    def test_computes_iv_from_out_of_the_money_legs(self):
        chain = {
            "calls": [
                {"strike": 100, "inTheMoney": False, "impliedVolatility": 0.30},
                {"strike": 90, "inTheMoney": True, "impliedVolatility": 0.10},
            ],
            "puts": [
                {"strike": 100, "inTheMoney": False, "impliedVolatility": 0.20},
            ],
        }
        with patch.object(DataFetcher, "get_options_chain", return_value=chain):
            result = DataFetcher.get_volatility_data("PETR4.SA")
        assert result is not None
        assert result["iv_call"] == pytest.approx(0.30)
        assert result["iv_put"] == pytest.approx(0.20)
        assert result["iv_avg"] == pytest.approx(0.25)

    def test_returns_none_when_chain_is_empty(self):
        with patch.object(DataFetcher, "get_options_chain", return_value=None):
            assert DataFetcher.get_volatility_data("NOCHAIN") is None


class TestGetMultipleQuotesAsync:
    @pytest.mark.asyncio
    async def test_gathers_quotes_concurrently(self):
        def fake_get_quote(symbol, use_cache=True):
            return {"ticker": symbol, "price": len(symbol)}

        with patch.object(DataFetcher, "get_quote", side_effect=fake_get_quote):
            result = await DataFetcher.get_multiple_quotes_async(["AAA", "BBBB"])

        assert result == {"AAA": {"ticker": "AAA", "price": 3}, "BBBB": {"ticker": "BBBB", "price": 4}}

    @pytest.mark.asyncio
    async def test_a_failing_symbol_becomes_none_without_failing_the_batch(self):
        def fake_get_quote(symbol, use_cache=True):
            if symbol == "BAD":
                raise RuntimeError("upstream error")
            return {"ticker": symbol}

        with patch.object(DataFetcher, "get_quote", side_effect=fake_get_quote):
            result = await DataFetcher.get_multiple_quotes_async(["GOOD", "BAD"])

        assert result["GOOD"] == {"ticker": "GOOD"}
        assert result["BAD"] is None

    @pytest.mark.asyncio
    async def test_a_cancelled_task_becomes_none_not_a_leaked_exception_object(self):
        """Regression test: gather(return_exceptions=True) can surface
        asyncio.CancelledError, a BaseException (not an Exception) — the
        filter must catch it too, or it leaks through as fake quote data."""
        async def fake_gather(*_tasks, return_exceptions=True):
            return [{"ticker": "OK"}, asyncio.CancelledError()]

        with patch.object(DataFetcher, "get_quote", return_value={"ticker": "unused"}), \
             patch("asyncio.gather", side_effect=fake_gather):
            result = await DataFetcher.get_multiple_quotes_async(["OK", "CANCELLED"])

        assert result["OK"] == {"ticker": "OK"}
        assert result["CANCELLED"] is None
