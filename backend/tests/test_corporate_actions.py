"""Point-in-time corporate-action rule. Synthetic prints only. No network."""

from __future__ import annotations

import inspect
from datetime import date
from pathlib import Path

import numpy as np
import pytest

from app.models.corporate_actions import (
    JUMP_RATIO,
    MAX_HEURISTIC_FACTOR,
    MIN_SHARE_QTY,
    OFFICIAL_RESIDUAL_TOL,
    OFFICIAL_SESSION_SLACK_DAYS,
    PRICE_INTEGER_REL_TOL,
    REVERT_NET_REL_TOL,
    REVERT_SESSIONS,
    VOLUME_LOG_REL_TOL,
    OfficialEvent,
    adj_return,
    adjust_prints,
    cash_scale_at,
    events_from_chart_splits,
    filing_price_multiplier,
    parse_cvm_ipe_text,
    parse_official_csv,
    summarize_audit,
)
from app.models.equal_weight import (
    CashEvent,
    Ledger,
    Position,
    Target,
    _credit,
    build_signal_book,
    event_arrays,
    simulate_book,
)
from app.models.equal_weight_io import Listing
from app.models.net_net import Company, SharePoint, Tape, trailing_adv


def _ord(year: int, month: int, day: int) -> int:
    return date(year, month, day).toordinal()


def _flat(n: int, price: float, qty: float, start: int | None = None) -> dict[str, np.ndarray]:
    origin = _ord(2023, 3, 1) if start is None else start
    dates = np.arange(origin, origin + n, dtype=np.int64)
    close = np.full(n, price, dtype=np.float64)
    return {
        "dates": dates,
        "close": close,
        "bid": close * 0.99,
        "ask": close * 1.01,
        "qty": np.full(n, qty, dtype=np.float64),
        "vol": close * qty,
    }


def test_pdgr3_style_grupamento_is_a_heuristic_and_not_a_return():
    tape = _flat(6, 1.0, 80_000.0)
    tape["close"][3:] = 80.0
    tape["bid"][3:] = 79.0
    tape["ask"][3:] = 81.0
    tape["qty"][3:] = 1_000.0
    tape["vol"][3:] = 80_000.0
    adj = adjust_prints(ticker="PDGR3", official=(), **tape)
    assert adj.source[3] == "heuristic"
    assert adj.share_factor[3] == pytest.approx(1.0 / 80.0)
    returns = adj_return(adj.close, adj.share_factor)
    assert returns[3] == pytest.approx(0.0, abs=1e-9)
    assert adj.audit[0]["source"] == "heuristic"
    assert adj.audit[0]["ticker"] == "PDGR3"
    assert adj.audit[0]["price_ratio"] == pytest.approx(80.0)

    # The motivating tape: price ×80 and share volume down 19.8×, inside the locked log band.
    loose = _flat(4, 1.0, 19_800.0)
    loose["close"][2:] = 80.0
    loose["qty"][2:] = 1_000.0
    loose_adj = adjust_prints(ticker="PDGR3", official=(), **loose)
    assert loose_adj.source[2] == "heuristic"
    assert loose_adj.share_factor[2] == pytest.approx(1.0 / 80.0)


def test_a_reversing_print_is_bad_data_and_not_a_corporate_action():
    tape = _flat(5, 10.0, 1_000.0)
    tape["close"][2] = 20.0
    tape["bid"][2] = 19.0
    tape["ask"][2] = 21.0
    tape["qty"][2] = 500.0
    tape["close"][3] = 10.0
    tape["qty"][3] = 1_000.0
    adj = adjust_prints(ticker="PDGR3", official=(), **tape)
    assert adj.source[2] == "bad_print"
    assert adj.source[3] == "bad_print"
    assert adj.share_factor[2] == pytest.approx(1.0)
    assert adj.close[2] == pytest.approx(10.0)
    assert not np.isfinite(adj.qty[2])
    returns = adj_return(adj.close, adj.share_factor)
    assert returns[2] == pytest.approx(0.0, abs=1e-9)
    assert returns[3] == pytest.approx(0.0, abs=1e-9)


def test_confirmed_split_uses_the_official_factor_only_when_it_was_already_known():
    tape = _flat(4, 20.0, 1_000.0)
    ex = int(tape["dates"][2])
    tape["close"][2:] = 10.0
    tape["bid"][2:] = 9.9
    tape["ask"][2:] = 10.1
    known = OfficialEvent("CONF3", ex, 2.0, ex - 10, "cvm", "desdobramento")
    adj = adjust_prints(ticker="CONF3", official=[known], **tape)
    assert adj.source[2] == "cvm"
    assert adj.share_factor[2] == pytest.approx(2.0)
    assert adj_return(adj.close, adj.share_factor)[2] == pytest.approx(0.0, abs=1e-9)

    late = OfficialEvent("CONF3", ex, 2.0, ex + 30, "cvm", "desdobramento")
    missed = adjust_prints(ticker="CONF3", official=[late], **tape)
    assert missed.source[2] == "unadjusted"
    assert missed.share_factor[2] == pytest.approx(1.0)
    assert "late_filing_ignored" in missed.audit[0]["reason"]
    summary = summarize_audit(missed.audit)
    assert summary["by_source"]["unadjusted"] == 1
    assert summary["late_filings_ignored"] == 1
    assert summary["eligible_for_live_trading"] is False


def test_a_price_spike_with_unchanged_share_volume_stays_in_the_return():
    tape = _flat(3, 1.0, 5_000.0)
    tape["close"][1] = 80.0
    tape["close"][2] = 80.0
    adj = adjust_prints(ticker="SPIK3", official=(), **tape)
    assert adj.source[1] == "unadjusted"
    assert adj.share_factor[1] == pytest.approx(1.0)
    assert adj_return(adj.close, adj.share_factor)[1] == pytest.approx(79.0)


def test_chart_ex_date_is_b3_and_a_later_protocol_does_not_override_a_mismatch():
    tape = _flat(3, 10.0, 2_000.0)
    ex = int(tape["dates"][1])
    tape["close"][1:] = 5.0
    chart = events_from_chart_splits("SPLIT3", [(ex, 2.0)])
    assert chart[0].source == "b3"
    assert chart[0].knowledge_ordinal == ex
    adj = adjust_prints(ticker="SPLIT3", official=chart, **tape)
    assert adj.source[1] == "b3"
    assert "chart_ex_date" in adj.audit[0]["reason"]
    assert summarize_audit(adj.audit)["b3_chart_ex_date"] == 1


def test_parsers_read_official_rows_and_ignore_a_subject_without_an_ex_date():
    csv_text = (
        "ticker,ex_date,share_factor,knowledge_date,source,kind\n"
        "PDGR3,2023-03-06,0.0125,2023-02-01,b3,grupamento\n"
    )
    parsed = parse_official_csv(csv_text)
    assert parsed[0].ticker == "PDGR3"
    assert parsed[0].share_factor == pytest.approx(1.0 / 80.0)
    assert parsed[0].usable
    ipe = (
        "CNPJ_Companhia;Assunto;Data_Entrega\n"
        "00.000.000/0001-91;Grupamento de PDGR3 na proporcao de 80 para 1, data-ex 06/03/2023;2023-02-01\n"
        "00.000.000/0001-91;Grupamento de PDGR3 na proporcao de 80 para 1;2023-02-01\n"
    )
    rows = parse_cvm_ipe_text(ipe)
    assert len(rows) == 1
    assert rows[0].source == "cvm"
    assert rows[0].share_factor == pytest.approx(1.0 / 80.0)
    assert rows[0].usable


def test_holding_through_the_grupamento_does_not_multiply_equity_and_scales_the_dividend():
    tape = _flat(12, 1.0, 80_000.0)
    tape["close"][8:] = 80.0
    tape["bid"][8:] = 79.2
    tape["ask"][8:] = 80.8
    tape["qty"][8:] = 1_000.0
    tape["vol"] = np.full(12, 5_000_000.0)
    adj = adjust_prints(ticker="PDGR3", official=(), **tape)
    held = Tape(
        tape["dates"],
        adj.close,
        adj.bid,
        adj.ask,
        adj.qty,
        adj.vol,
        adj.share_factor,
        adj.source,
        adj.heuristic_cash_scale,
    )
    sessions = [int(day) for day in tape["dates"]]
    book = {sessions[3]: [Target("1", "PDGR3", 5_000_000.0, 80_000.0)]}
    events = event_arrays({"PDGR3": [CashEvent(sessions[8], 0.1, "dividendo")]}, 0.0)
    run = simulate_book(sessions, {"PDGR3": held}, book, 1_000_000.0, events, exit_when_stale=False)
    assert run["eligible_for_live_trading"] is False
    assert run["net"][8] < run["net"][7] * 1.5
    assert run["net"][8] > run["net"][7] * 0.7
    net = Ledger(0.0, {"PDGR3": Position("1", "PDGR3", 100.0, 1.0, sessions[0])})
    gross = Ledger(0.0, {"PDGR3": Position("1", "PDGR3", 100.0, 1.0, sessions[0])})
    paid, count = _credit(net, gross, events, sessions[7], sessions[8], {"PDGR3": held})
    assert count == 1
    assert paid == pytest.approx(0.1 * cash_scale_at(held, sessions[8]) * 100.0)
    assert cash_scale_at(held, sessions[8]) == pytest.approx(80.0)


def test_market_cap_and_share_adv_use_the_factor_after_the_filing():
    start = _ord(2018, 6, 1)
    n = 40
    dates = np.arange(start, start + n, dtype=np.int64)
    close = np.full(n, 10.0)
    close[30:] = 100.0
    split = np.ones(n)
    split[30] = 0.1
    qty = np.full(n, 8_000.0)
    vol = np.full(n, 1_000_000.0)
    tape = Tape(dates, close, close, close, qty, vol, split)
    _brl, shares = trailing_adv(tape, 31)
    assert shares == pytest.approx(800.0)
    assert _brl == pytest.approx(1_000_000.0)
    point = SharePoint(_ord(2014, 12, 31), _ord(2015, 1, 2), 1_000.0, 0.0, 1_000.0, 0.0)
    company = Company("1", "1", "Têxtil", "ATIVO", [], [], [point], [], [], [])
    other = Company("2", "2", "Têxtil", "ATIVO", [], [], [point], [], [], [])
    listings = [Listing("1", "AAA3", start, None, "on"), Listing("2", "BBB3", start, None, "on")]
    quiet = Tape(dates, np.full(n, 10.0), np.full(n, 10.0), np.full(n, 10.0), qty, vol, np.ones(n))
    signal = start + 35
    book = build_signal_book([company, other], listings, {"AAA3": tape, "BBB3": quiet}, [signal], "small", 50_000.0, min_names=1)
    caps = {row.ticker: row.mcap for row in book[signal]}
    assert caps["AAA3"] == pytest.approx(10_000.0)
    assert filing_price_multiplier(dates, split, point.received, signal) == pytest.approx(0.1)


def test_documented_tolerances_match_the_locked_constants():
    text = (Path(__file__).resolve().parents[2] / "docs" / "EQUAL-WEIGHT-B3.md").read_text(encoding="utf-8")
    expected = [
        f"{JUMP_RATIO:.2f}".replace(".", ","),
        f"{PRICE_INTEGER_REL_TOL:.0%}",
        f"2 a {MAX_HEURISTIC_FACTOR}",
        f"{VOLUME_LOG_REL_TOL:.2f}".replace(".", ","),
        f"mínimo de {int(MIN_SHARE_QTY)} ações",
        f"{REVERT_SESSIONS} pregões",
        f"{REVERT_NET_REL_TOL:.0%}",
        f"{OFFICIAL_RESIDUAL_TOL:.0%}",
        f"{OFFICIAL_SESSION_SLACK_DAYS} dias",
    ]
    for snippet in expected:
        assert snippet in text
    assert "250 dias" in text
    assert "eligible_for_live_trading" in text
    source = inspect.getsource(__import__("app.models.corporate_actions", fromlist=["adjust_prints"]))
    for banned in ("urllib", "requests", "httpx", "socket", "urlopen"):
        assert banned not in source
