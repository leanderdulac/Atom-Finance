"""Ibovespa universe refresh: skip tickers without quotes, JBS BDR ticker."""
from unittest.mock import patch

import pytest

from app.models import ibovespa
from app.models.ibovespa import IBOVESPA_ASSETS, refresh_ibovespa_params
from app.models.options_agent import OptionsExpert


@pytest.fixture(autouse=True)
def _reset_refresh_clock():
    previous = ibovespa._LAST_REFRESH
    ibovespa._LAST_REFRESH = None
    yield
    ibovespa._LAST_REFRESH = previous


def test_universe_uses_jbs_bdr_not_delisted_ordinary():
    tickers = [asset["ticker"] for asset in IBOVESPA_ASSETS]
    assert "JBSS32" in tickers
    assert "JBSS3" not in tickers
    assert "JBSS32" in OptionsExpert.TOP_B3_TICKERS
    assert "JBSS3" not in OptionsExpert.TOP_B3_TICKERS


@pytest.mark.asyncio
async def test_refresh_skips_tickers_without_price_and_does_not_call_kronos():
    petr = next(asset for asset in IBOVESPA_ASSETS if asset["ticker"] == "PETR4")
    jbs = next(asset for asset in IBOVESPA_ASSETS if asset["ticker"] == "JBSS32")
    petr_s0, jbs_s0, petr_mu = petr["S0"], jbs["S0"], petr["mu"]

    quotes = {
        "PETR4.SA": {"price": 41.5},
        "JBSS32.SA": {"price": 0},
    }

    try:
        with patch("app.models.ibovespa.DataFetcher.get_multiple_quotes_async", return_value=quotes), \
             patch("app.models.kronos_agent.KronosAgent.predict", return_value=None) as predict:
            assert await refresh_ibovespa_params(force=True) is True

        assert petr["S0"] == 41.5
        assert jbs["S0"] == jbs_s0  # unchanged when quote has no usable price
        predict.assert_called_once_with("PETR4.SA", 30)
    finally:
        petr["S0"] = petr_s0
        petr["mu"] = petr_mu
        jbs["S0"] = jbs_s0
