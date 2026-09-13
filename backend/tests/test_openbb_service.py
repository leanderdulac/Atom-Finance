"""Tests for OpenBBService — mocks the `_get_openbb()` boundary (the lazy,
optional OpenBB SDK import) and exercises our own output-normalisation and
error-handling logic around it."""
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from app.services.openbb_service import OpenBBService


def _patch_obb(obb_mock):
    return patch("app.services.openbb_service._get_openbb", return_value=obb_mock)


class TestAvailability:
    def test_is_available_false_when_sdk_missing(self):
        with patch("app.services.openbb_service._get_openbb", return_value=None):
            assert OpenBBService.is_available() is False

    def test_is_available_true_when_sdk_present(self):
        with patch("app.services.openbb_service._get_openbb", return_value=MagicMock()):
            assert OpenBBService.is_available() is True

    def test_get_provider_status_shape(self):
        with patch("app.services.openbb_service._get_openbb", return_value=MagicMock()):
            status = OpenBBService.get_provider_status()
        assert status["openbb_available"] is True
        assert status["default_openbb_providers"]["quote"] == "yfinance"


class TestOutputToDataframe:
    def test_none_output_returns_empty_dataframe(self):
        assert OpenBBService._output_to_dataframe(None).empty

    def test_uses_to_df_method_when_available(self):
        expected = pd.DataFrame([{"a": 1}])
        output = MagicMock()
        output.to_df.return_value = expected
        result = OpenBBService._output_to_dataframe(output)
        assert result.equals(expected)

    def test_falls_back_to_results_attribute_dataframe(self):
        output = MagicMock(spec=["results"])
        output.results = pd.DataFrame([{"b": 2}])
        result = OpenBBService._output_to_dataframe(output)
        assert result.equals(output.results)

    def test_normalises_list_of_pydantic_like_results(self):
        item = MagicMock()
        item.model_dump.return_value = {"symbol": "AAPL"}
        output = MagicMock(spec=["results"])
        output.results = [item]
        result = OpenBBService._output_to_dataframe(output)
        assert result.to_dict("records") == [{"symbol": "AAPL"}]

    def test_normalises_list_of_plain_dicts(self):
        output = MagicMock(spec=["results"])
        output.results = [{"x": 1}, {"x": 2}]
        result = OpenBBService._output_to_dataframe(output)
        assert len(result) == 2

    def test_dict_results_become_dataframe(self):
        output = MagicMock(spec=["results"])
        output.results = {"col": [1, 2, 3]}
        result = OpenBBService._output_to_dataframe(output)
        assert list(result["col"]) == [1, 2, 3]

    def test_unrecognised_shape_returns_empty_dataframe(self):
        output = MagicMock(spec=["results"])
        output.results = 12345
        assert OpenBBService._output_to_dataframe(output).empty


class TestGetQuote:
    def test_returns_none_when_sdk_unavailable(self):
        with _patch_obb(None):
            assert OpenBBService.get_quote("AAPL") is None

    def test_returns_none_when_output_is_empty(self):
        obb = MagicMock()
        obb.equity.price.quote.return_value = MagicMock(spec=["results"], results=[])
        with _patch_obb(obb):
            assert OpenBBService.get_quote("AAPL") is None

    def test_shapes_quote_and_derives_change_when_missing(self):
        row = {"last_price": 150.0, "prev_close": 148.0, "volume": 1000, "name": "Apple Inc."}
        obb = MagicMock()
        obb.equity.price.quote.return_value = MagicMock(spec=["results"], results=[row])
        with _patch_obb(obb):
            result = OpenBBService.get_quote("aapl", provider="yfinance")

        assert result["ticker"] == "AAPL"
        assert result["price"] == 150.0
        assert result["change"] == pytest.approx(2.0)  # derived: 150 - 148
        assert result["change_pct"] == pytest.approx((2.0 / 148.0) * 100)
        assert result["provider"] == "openbb::yfinance"

    def test_returns_none_on_exception(self):
        obb = MagicMock()
        obb.equity.price.quote.side_effect = RuntimeError("provider down")
        with _patch_obb(obb):
            assert OpenBBService.get_quote("AAPL") is None


class TestGetHistoricalData:
    def test_returns_none_when_empty(self):
        obb = MagicMock()
        obb.equity.price.historical.return_value = MagicMock(spec=["results"], results=[])
        with _patch_obb(obb):
            assert OpenBBService.get_historical_data("AAPL") is None

    def test_sorts_and_indexes_by_date(self):
        rows = [
            {"date": "2024-01-02", "close": 2.0},
            {"date": "2024-01-01", "close": 1.0},
        ]
        obb = MagicMock()
        obb.equity.price.historical.return_value = MagicMock(spec=["results"], results=rows)
        with _patch_obb(obb):
            result = OpenBBService.get_historical_data("AAPL")
        assert result is not None
        assert list(result["close"]) == [1.0, 2.0]
        assert result.index.name == "date"

    def test_returns_none_on_exception(self):
        obb = MagicMock()
        obb.equity.price.historical.side_effect = ValueError("bad date range")
        with _patch_obb(obb):
            assert OpenBBService.get_historical_data("AAPL") is None


class TestGetProfile:
    def test_shapes_profile_fields(self):
        row = {"name": "Apple Inc.", "sector": "Technology", "stock_exchange": "NASDAQ"}
        obb = MagicMock()
        obb.equity.profile.return_value = MagicMock(spec=["results"], results=[row])
        with _patch_obb(obb):
            result = OpenBBService.get_profile("AAPL")
        assert result["name"] == "Apple Inc."
        assert result["exchange"] == "NASDAQ"

    def test_returns_none_when_sdk_unavailable(self):
        with _patch_obb(None):
            assert OpenBBService.get_profile("AAPL") is None


class TestSearchEquity:
    def test_returns_records_from_preferred_provider(self):
        obb = MagicMock()
        obb.equity.search.return_value = MagicMock(spec=["results"], results=[{"symbol": "AAPL"}])
        with _patch_obb(obb):
            result = OpenBBService.search_equity("apple", provider="sec")
        assert result[0]["symbol"] == "AAPL"
        assert result[0]["provider"] == "openbb::sec"

    def test_falls_back_to_next_provider_when_first_fails(self):
        obb = MagicMock()
        obb.equity.search.side_effect = [
            RuntimeError("sec down"),
            MagicMock(spec=["results"], results=[{"symbol": "AAPL"}]),
        ]
        with _patch_obb(obb):
            result = OpenBBService.search_equity("apple", provider="sec")
        assert result[0]["provider"] == "openbb::cboe"

    def test_returns_empty_list_when_all_providers_fail(self):
        obb = MagicMock()
        obb.equity.search.side_effect = RuntimeError("down")
        with _patch_obb(obb):
            assert OpenBBService.search_equity("apple") == []

    def test_returns_empty_list_when_sdk_unavailable(self):
        with _patch_obb(None):
            assert OpenBBService.search_equity("apple") == []


class TestGetOptionsChain:
    def test_returns_none_when_empty(self):
        obb = MagicMock()
        obb.derivatives.options.chains.return_value = MagicMock(spec=["results"], results=[])
        with _patch_obb(obb):
            assert OpenBBService.get_options_chain("AAPL") is None

    def test_groups_legs_by_expiration_and_strike(self):
        rows = [
            {"expiration": "2025-01-17", "strike": 150.0, "option_type": "call",
             "last_trade_price": 5.0, "delta": 0.5, "implied_volatility": 0.3, "volume": 10, "open_interest": 100},
            {"expiration": "2025-01-17", "strike": 150.0, "option_type": "put",
             "last_trade_price": 4.0, "delta": -0.5, "implied_volatility": 0.28, "volume": 5, "open_interest": 50},
        ]
        obb = MagicMock()
        obb.derivatives.options.chains.return_value = MagicMock(spec=["results"], results=rows)
        with _patch_obb(obb):
            result = OpenBBService.get_options_chain("AAPL")

        assert result is not None
        assert result["ticker"] == "AAPL"
        assert len(result["chain"]) == 1  # one (expiration, strike) group
        leg = result["chain"][0]
        assert leg["call_price"] == 5.0
        assert leg["put_price"] == 4.0
        assert leg["volume"] == 15  # 10 + 5 summed across legs

    def test_returns_none_on_exception(self):
        obb = MagicMock()
        obb.derivatives.options.chains.side_effect = RuntimeError("cboe down")
        with _patch_obb(obb):
            assert OpenBBService.get_options_chain("AAPL") is None

    def test_returns_none_when_sdk_unavailable(self):
        with _patch_obb(None):
            assert OpenBBService.get_options_chain("AAPL") is None
