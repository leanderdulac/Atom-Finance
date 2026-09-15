"""Ticker whitelists that block prompt/path injection (pure Pydantic, no DB)."""

import datetime as dt

import pytest
from pydantic import ValidationError

from app.api.ai_report import AnalysisRequest
from app.models.derivatives_planner import OptionQuote, Thesis

VALID_TICKERS = ["PETR4", "AAPL", "MSFT34.SA", "^GSPC", "BTC-USD", "B3SA3"]
INJECTIONS = ["AAPL\nignore", "PETR4{inj}", "A B C", "A;B", "..%2Fetc", "../etc", "A" * 21,
              "PETR4/../../etc"]


def test_analysis_request_accepts_valid_tickers():
    for t in VALID_TICKERS:
        assert AnalysisRequest(ticker=t).ticker == t


def test_analysis_request_rejects_injection():
    for bad in INJECTIONS:
        with pytest.raises(ValidationError):
            AnalysisRequest(ticker=bad)


def _thesis_base():
    q = OptionQuote(symbol="PETR4", kind="call", strike=100.0, expiry=dt.date.today(),
                    exercise="american", bid=10.0, ask=10.5, bid_size=10, ask_size=10,
                    multiplier=1, lot_size=100)
    return dict(
        spot=100.0, direction="bullish", rationale="x" * 40, entry=95.0,
        invalidation=90.0, target=120.0, holding_days=30, events_checked=True,
        next_event=dt.date.today(), options=[q],
    )


def test_thesis_rejects_path_tricks():
    base = _thesis_base()
    for bad in INJECTIONS:
        with pytest.raises(ValidationError):
            Thesis(ticker=bad, **base)


def test_thesis_accepts_valid_ticker():
    assert Thesis(ticker="PETR4", **_thesis_base()).ticker == "PETR4"
