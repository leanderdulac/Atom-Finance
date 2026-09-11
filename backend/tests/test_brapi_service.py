"""Tests for BrapiService — mocks the `requests` boundary, exercises our own
caching, response-shaping, and malformed-data handling around brapi.dev."""
from unittest.mock import MagicMock, patch

import pytest
import requests

from app.services.brapi_service import BrapiService, _is_br_ticker


class TestIsBrTicker:
    @pytest.mark.parametrize("ticker", ["PETR4", "VALE3", "ITUB4", "BBAS3", "ITUB4F"])
    def test_recognizes_br_tickers(self, ticker):
        assert _is_br_ticker(ticker) is True

    @pytest.mark.parametrize("ticker", ["AAPL", "GOOGL", "TSLA", "SPY", "BTC-USD"])
    def test_rejects_us_tickers(self, ticker):
        assert _is_br_ticker(ticker) is False


def _mock_response(json_data, status_ok=True):
    resp = MagicMock()
    resp.json.return_value = json_data
    if status_ok:
        resp.raise_for_status.return_value = None
    else:
        resp.raise_for_status.side_effect = requests.HTTPError("error")
    return resp


class TestGetQuote:
    def test_returns_cached_value_without_hitting_the_network(self):
        cached = {"ticker": "PETR4", "price": 38.0}
        with patch("app.services.brapi_service.Cache.get", return_value=cached), \
             patch("app.services.brapi_service.requests.get") as req_get:
            result = BrapiService.get_quote("petr4")
            req_get.assert_not_called()
        assert result == cached

    def test_fetches_and_shapes_quote_on_cache_miss(self):
        payload = {"results": [{
            "symbol": "PETR4", "regularMarketPrice": 38.5, "regularMarketChange": 0.5,
            "regularMarketChangePercent": 1.3, "regularMarketVolume": 1000000,
            "regularMarketDayHigh": 39.0, "regularMarketDayLow": 37.5,
            "marketCap": 500_000_000_000, "longName": "Petrobras", "currency": "BRL",
        }]}
        with patch("app.services.brapi_service.Cache.get", return_value=None), \
             patch("app.services.brapi_service.Cache.set") as cache_set, \
             patch("app.services.brapi_service.requests.get", return_value=_mock_response(payload)):
            result = BrapiService.get_quote("petr4")

        assert result["ticker"] == "PETR4"
        assert result["price"] == 38.5
        assert result["name"] == "Petrobras"
        cache_set.assert_called_once()

    def test_returns_none_when_no_results(self):
        with patch("app.services.brapi_service.Cache.get", return_value=None), \
             patch("app.services.brapi_service.requests.get", return_value=_mock_response({"results": []})):
            assert BrapiService.get_quote("NOTFOUND") is None

    def test_returns_none_on_http_error(self):
        with patch("app.services.brapi_service.Cache.get", return_value=None), \
             patch("app.services.brapi_service.requests.get", return_value=_mock_response({}, status_ok=False)):
            assert BrapiService.get_quote("PETR4") is None

    def test_returns_none_on_network_error(self):
        with patch("app.services.brapi_service.Cache.get", return_value=None), \
             patch("app.services.brapi_service.requests.get", side_effect=requests.ConnectionError("down")):
            assert BrapiService.get_quote("PETR4") is None

    def test_missing_numeric_fields_default_to_zero_not_none(self):
        payload = {"results": [{"symbol": "XYZ3"}]}  # no price fields at all
        with patch("app.services.brapi_service.Cache.get", return_value=None), \
             patch("app.services.brapi_service.Cache.set"), \
             patch("app.services.brapi_service.requests.get", return_value=_mock_response(payload)):
            result = BrapiService.get_quote("XYZ3")
        assert result["price"] == 0.0
        assert result["volume"] == 0


class TestGetQuotesBatch:
    def test_empty_input_returns_empty_dict_without_a_request(self):
        with patch("app.services.brapi_service.requests.get") as req_get:
            result = BrapiService.get_quotes_batch([])
            req_get.assert_not_called()
        assert result == {}

    def test_builds_comma_separated_url_and_shapes_each_result(self):
        payload = {"results": [
            {"symbol": "PETR4", "regularMarketPrice": 38.0},
            {"symbol": "VALE3", "regularMarketPrice": 65.0},
        ]}
        with patch("app.services.brapi_service.Cache.get", return_value=None), \
             patch("app.services.brapi_service.Cache.set"), \
             patch("app.services.brapi_service.requests.get", return_value=_mock_response(payload)) as req_get:
            result = BrapiService.get_quotes_batch(["petr4", "vale3"])

        called_url = req_get.call_args[0][0]
        assert "PETR4,VALE3" in called_url
        assert set(result.keys()) == {"PETR4", "VALE3"}
        assert result["PETR4"]["price"] == 38.0

    def test_skips_results_with_no_symbol(self):
        payload = {"results": [{"regularMarketPrice": 1.0}, {"symbol": "OK3", "regularMarketPrice": 2.0}]}
        with patch("app.services.brapi_service.Cache.get", return_value=None), \
             patch("app.services.brapi_service.Cache.set"), \
             patch("app.services.brapi_service.requests.get", return_value=_mock_response(payload)):
            result = BrapiService.get_quotes_batch(["ok3"])
        assert list(result.keys()) == ["OK3"]

    def test_returns_empty_dict_on_exception(self):
        with patch("app.services.brapi_service.Cache.get", return_value=None), \
             patch("app.services.brapi_service.requests.get", side_effect=requests.Timeout("slow")):
            assert BrapiService.get_quotes_batch(["PETR4"]) == {}


class TestGetHistory:
    def _payload(self, bars):
        return {"results": [{"currency": "BRL", "historicalDataPrice": bars}]}

    def test_shapes_and_sorts_bars_by_date(self):
        bars = [
            {"date": 1704412800, "open": 10, "high": 11, "low": 9, "close": 10.5, "volume": 100},
            {"date": 1704067200, "open": 9, "high": 10, "low": 8, "close": 9.5, "volume": 50},
        ]
        with patch("app.services.brapi_service.Cache.get", return_value=None), \
             patch("app.services.brapi_service.Cache.set"), \
             patch("app.services.brapi_service.requests.get", return_value=_mock_response(self._payload(bars))):
            result = BrapiService.get_history("PETR4", days=252)

        assert result is not None
        # sorted ascending by date: the earlier bar comes first
        assert result["close"] == [9.5, 10.5]

    def test_skips_bars_with_missing_or_invalid_close(self):
        bars = [
            {"date": 1704067200, "close": None},
            {"date": 1704153600, "close": "not-a-number"},
            {"date": 1704240000, "close": 0},  # non-positive, skipped
            {"date": 1704326400, "close": 12.34},
        ]
        with patch("app.services.brapi_service.Cache.get", return_value=None), \
             patch("app.services.brapi_service.Cache.set"), \
             patch("app.services.brapi_service.requests.get", return_value=_mock_response(self._payload(bars))):
            result = BrapiService.get_history("PETR4")
        assert result["close"] == [12.34]

    def test_returns_none_when_no_valid_bars_remain(self):
        bars = [{"date": 1704067200, "close": None}]
        with patch("app.services.brapi_service.Cache.get", return_value=None), \
             patch("app.services.brapi_service.requests.get", return_value=_mock_response(self._payload(bars))):
            assert BrapiService.get_history("PETR4") is None

    def test_returns_none_when_no_results(self):
        with patch("app.services.brapi_service.Cache.get", return_value=None), \
             patch("app.services.brapi_service.requests.get", return_value=_mock_response({"results": []})):
            assert BrapiService.get_history("PETR4") is None

    def test_picks_closest_brapi_range_for_requested_days(self):
        bars = [{"date": 1704067200, "close": 10.0}]
        with patch("app.services.brapi_service.Cache.get", return_value=None), \
             patch("app.services.brapi_service.Cache.set"), \
             patch("app.services.brapi_service.requests.get", return_value=_mock_response(self._payload(bars))) as req_get:
            BrapiService.get_history("PETR4", days=100)  # closer to 126 (6mo) than 66 (3mo)
        assert req_get.call_args.kwargs["params"]["range"] == "6mo"


class TestListTickers:
    def test_returns_ticker_list(self):
        payload = {"stocks": [{"stock": "PETR4"}, {"stock": "VALE3"}, {}]}
        with patch("app.services.brapi_service.Cache.get", return_value=None), \
             patch("app.services.brapi_service.Cache.set"), \
             patch("app.services.brapi_service.requests.get", return_value=_mock_response(payload)):
            result = BrapiService.list_tickers()
        assert result == ["PETR4", "VALE3"]

    def test_returns_empty_list_on_exception(self):
        with patch("app.services.brapi_service.Cache.get", return_value=None), \
             patch("app.services.brapi_service.requests.get", side_effect=requests.ConnectionError("down")):
            assert BrapiService.list_tickers() == []


class TestMacroEndpoints:
    def test_get_inflation_returns_data(self):
        with patch("app.services.brapi_service.Cache.get", return_value=None), \
             patch("app.services.brapi_service.Cache.set"), \
             patch("app.services.brapi_service.requests.get", return_value=_mock_response({"ipca": 4.5})):
            assert BrapiService.get_inflation() == {"ipca": 4.5}

    def test_get_prime_rate_returns_none_on_failure(self):
        with patch("app.services.brapi_service.Cache.get", return_value=None), \
             patch("app.services.brapi_service.requests.get", side_effect=requests.Timeout()):
            assert BrapiService.get_prime_rate() is None


class TestHealthCheck:
    def test_error_when_token_missing(self, monkeypatch):
        monkeypatch.delenv("BRAPI_TOKEN", raising=False)
        result = BrapiService.health_check()
        assert result["status"] == "error"

    def test_healthy_when_tickers_returned(self, monkeypatch):
        monkeypatch.setenv("BRAPI_TOKEN", "tok")
        with patch.object(BrapiService, "list_tickers", return_value=["PETR4", "VALE3"]):
            result = BrapiService.health_check()
        assert result == {"status": "healthy", "ticker_count": 2}

    def test_degraded_when_no_tickers_returned(self, monkeypatch):
        monkeypatch.setenv("BRAPI_TOKEN", "tok")
        with patch.object(BrapiService, "list_tickers", return_value=[]):
            result = BrapiService.health_check()
        assert result["status"] == "degraded"
