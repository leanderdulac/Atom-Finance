"""Public regime books — mocked Yahoo + FRED, no network."""
from __future__ import annotations

import pandas as pd

from app.models.regime import demo_payload, evaluate, regime_probs
from app.services.regime_feeds import EQUITY_TICKERS, fetch_live_payload
from app.services.regime_job import job_enabled, run_snapshot


def _hist(idx: pd.DatetimeIndex):
    def hist(sym: str) -> pd.Series:
        n = len(idx)
        if sym == "^VIX":
            return pd.Series([15.0] * n, index=idx)
        if "VIX3M" in sym or sym == "^VXV":
            return pd.Series([17.0] * n, index=idx)
        if sym == "^TNX":
            return pd.Series([4.2] * n, index=idx)
        if sym == "^IRX":
            return pd.Series([3.8] * n, index=idx)
        return pd.Series(100.0 + pd.RangeIndex(n).to_numpy() * 0.02, index=idx)
    return hist


def test_fetch_live_payload_aligns_without_network():
    idx = pd.bdate_range("2023-01-03", periods=280)
    oas = lambda: pd.Series(340.0, index=idx, name="credit")  # noqa: E731
    out = fetch_live_payload(history_fn=_hist(idx), oas_fn=oas)
    assert out["live_books"] is True
    assert out["sources"]["credit"].startswith("FRED")
    assert len(out["vix_front"]) >= 120
    for t in EQUITY_TICKERS:
        assert t in out["equity_prices"]
    ev = evaluate(
        equity_prices=out["equity_prices"],
        vix_front=out["vix_front"],
        vix_back=out["vix_back"],
        implied_vol=out["implied_vol"],
        credit_spread=out["credit_spread"],
        yield_2y=out["yield_2y"],
        yield_10y=out["yield_10y"],
        window=90,
    )
    assert ev["probs"]
    assert abs(sum(ev["probs"].values()) - 1.0) < 1e-6
    assert ev["holdout"]["n"] > 0


def test_run_snapshot_uses_injected_fetch():
    idx = pd.bdate_range("2023-01-03", periods=280)
    payload = fetch_live_payload(
        history_fn=_hist(idx),
        oas_fn=lambda: pd.Series(340.0, index=idx, name="credit"),
    )
    snap = run_snapshot(fetch=lambda: payload)
    assert snap["live_books"] is True
    assert snap["eligible_for_live_trading"] is False


def test_job_disabled_in_test_env(monkeypatch):
    monkeypatch.setenv("ATOM_ENV", "test")
    monkeypatch.setenv("ATOM_REGIME_JOB", "1")
    assert job_enabled() is False


def test_softmax_and_holdout_on_crisis_demo():
    out = evaluate(**demo_payload("crisis"))
    assert abs(sum(out["probs"].values()) - 1.0) < 1e-6
    assert max(out["probs"], key=out["probs"].get) == "crisis"
    assert out["holdout"]["n"] > 20
    assert out["holdout"]["accuracy"] is not None


def test_regime_probs_sum_to_one():
    snaps = {
        "hurst": {"percentile": 80},
        "vix_term_structure": {"percentile": 20},
        "rv_iv_spread": {"percentile": 40},
        "cross_asset_corr": {"percentile": 90},
        "credit_spread": {"percentile": 92},
        "rates_curve_slope": {"percentile": 5},
    }
    p = regime_probs(snaps)
    assert abs(sum(p.values()) - 1.0) < 1e-6
    assert p["crisis"] == max(p.values())
