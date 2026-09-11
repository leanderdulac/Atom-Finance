"""Tests for KronosAgent — the ATOM-specific wrapper around the vendored
Kronos model. Mocks the predictor and DataFetcher boundaries; the vendored
model itself (app/models/kronos/) is out of scope, same as any other
third-party dependency."""
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from app.models.kronos_agent import KronosAgent


@pytest.fixture(autouse=True)
def reset_singleton():
    """KronosAgent caches its predictor on the class itself; reset between
    tests so one test's mock doesn't leak into the next."""
    KronosAgent._predictor = None
    yield
    KronosAgent._predictor = None


def _fake_history(n=30, tz=None):
    dates = pd.date_range("2024-01-01", periods=n, freq="D", tz=tz)
    return pd.DataFrame({
        "Date": dates,
        "Open": [100.0 + i for i in range(n)],
        "High": [101.0 + i for i in range(n)],
        "Low": [99.0 + i for i in range(n)],
        "Close": [100.5 + i for i in range(n)],
        "Volume": [1000] * n,
    }).set_index("Date").reset_index()


class TestGetPredictor:
    def test_returns_none_and_does_not_raise_when_model_fails_to_load(self):
        with patch("app.models.kronos.KronosTokenizer.from_pretrained", side_effect=RuntimeError("no network")):
            result = KronosAgent.get_predictor()
        assert result is None

    def test_caches_the_predictor_after_first_successful_load(self):
        fake_predictor = MagicMock()
        with patch("app.models.kronos.KronosTokenizer.from_pretrained", return_value=MagicMock()), \
             patch("app.models.kronos.Kronos.from_pretrained", return_value=MagicMock()), \
             patch("app.models.kronos.KronosPredictor", return_value=fake_predictor) as predictor_cls:
            first = KronosAgent.get_predictor()
            second = KronosAgent.get_predictor()

        assert first is fake_predictor
        assert second is fake_predictor
        predictor_cls.assert_called_once()  # only initialized once, then cached


class TestPredict:
    def test_returns_none_when_predictor_unavailable(self):
        with patch.object(KronosAgent, "get_predictor", return_value=None):
            result = KronosAgent.predict("PETR4.SA")
        assert result is None

    def test_returns_none_when_no_historical_data(self):
        with patch.object(KronosAgent, "get_predictor", return_value=MagicMock()), \
             patch("app.models.kronos_agent.DataFetcher.get_historical_data", return_value=None):
            result = KronosAgent.predict("PETR4.SA")
        assert result is None

    def test_returns_none_when_historical_data_is_empty(self):
        with patch.object(KronosAgent, "get_predictor", return_value=MagicMock()), \
             patch("app.models.kronos_agent.DataFetcher.get_historical_data", return_value=pd.DataFrame()):
            result = KronosAgent.predict("PETR4.SA")
        assert result is None

    def test_bullish_prediction_shape(self):
        hist = _fake_history(n=30)
        predictor = MagicMock()
        pred_df = pd.DataFrame({"close": [200.0] * 30})  # well above last close -> bullish
        predictor.predict.return_value = pred_df

        with patch.object(KronosAgent, "get_predictor", return_value=predictor), \
             patch("app.models.kronos_agent.DataFetcher.get_historical_data", return_value=hist):
            result = KronosAgent.predict("PETR4.SA", pred_len=30)

        assert result is not None
        assert result["symbol"] == "PETR4.SA"
        assert result["trend"] == "BULLISH"
        assert result["predicted_return_pct"] > 0
        assert result["lookback_days"] == 30
        assert result["pred_len_days"] == 30

    def test_bearish_prediction_when_price_falls(self):
        hist = _fake_history(n=30)
        predictor = MagicMock()
        pred_df = pd.DataFrame({"close": [1.0] * 30})  # well below last close -> bearish
        predictor.predict.return_value = pred_df

        with patch.object(KronosAgent, "get_predictor", return_value=predictor), \
             patch("app.models.kronos_agent.DataFetcher.get_historical_data", return_value=hist):
            result = KronosAgent.predict("PETR4.SA")

        assert result["trend"] == "BEARISH"
        assert result["predicted_return_pct"] < 0

    def test_trims_lookback_to_512_when_history_is_longer(self):
        hist = _fake_history(n=600)
        predictor = MagicMock()
        pred_df = pd.DataFrame({"close": [700.0] * 30})
        predictor.predict.return_value = pred_df

        with patch.object(KronosAgent, "get_predictor", return_value=predictor), \
             patch("app.models.kronos_agent.DataFetcher.get_historical_data", return_value=hist):
            result = KronosAgent.predict("PETR4.SA")

        assert result["lookback_days"] == 512

    def test_strips_timezone_from_dates(self):
        hist = _fake_history(n=30, tz="America/Sao_Paulo")
        predictor = MagicMock()
        pred_df = pd.DataFrame({"close": [200.0] * 30})
        predictor.predict.return_value = pred_df

        with patch.object(KronosAgent, "get_predictor", return_value=predictor), \
             patch("app.models.kronos_agent.DataFetcher.get_historical_data", return_value=hist):
            result = KronosAgent.predict("PETR4.SA")

        assert result is not None  # would raise if the tz-aware date leaked into date_range()

    def test_returns_none_and_does_not_raise_when_predict_fails(self):
        hist = _fake_history(n=30)
        predictor = MagicMock()
        predictor.predict.side_effect = RuntimeError("CUDA out of memory")

        with patch.object(KronosAgent, "get_predictor", return_value=predictor), \
             patch("app.models.kronos_agent.DataFetcher.get_historical_data", return_value=hist):
            result = KronosAgent.predict("PETR4.SA")

        assert result is None
