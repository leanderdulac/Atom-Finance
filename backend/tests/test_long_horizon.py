"""Long-horizon factor rules. Fixtures only: this module does not open a socket."""

from __future__ import annotations

import inspect
from datetime import date, timedelta

import numpy as np
import pytest

from app.models import long_horizon, net_net_io
from app.models.long_horizon import (
    DESIGN_END,
    EVAL_START,
    FAMILY_ID,
    LIQUIDITY_ADV_BRL,
    SELECTION_AUM,
    Candidate,
    adjusted_close,
    build_candidates,
    choose_specification,
    momentum_12_1,
    prepare_tapes,
    production_grid,
    quality_components,
    score_factor,
    signal_book,
    top_quintile,
)
from app.models.net_net import BsPoint, Company, EarnRow, Tape
from app.models.net_net_io import assemble_companies, cdi_growth, parse_sgs_cdi, parse_statement


def _ord(year: int, month: int, day: int) -> int:
    return date(year, month, day).toordinal()


def _month_end(year: int, month: int) -> int:
    nxt = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
    day = nxt - timedelta(days=1)
    while day.weekday() >= 5:
        day -= timedelta(days=1)
    return day.toordinal()


def _tape(ords, close, qty=200_000.0) -> Tape:
    close = np.asarray(close, dtype=np.float64)
    n = len(ords)
    return Tape(
        dates=np.asarray(ords, dtype=np.int64),
        close=close,
        bid=close * 0.999,
        ask=close * 1.001,
        qty=np.full(n, qty),
        vol=close * qty,
        split=np.ones(n),
    )


def test_adjusted_close_removes_a_confirmed_grupamento():
    # Price jumps 10x while shares fall 10x. The economic price is unchanged.
    close = np.array([1.0, 10.0, 10.0])
    split = np.array([1.0, 0.1, 1.0])
    assert adjusted_close(close, split) == pytest.approx([10.0, 10.0, 10.0])


def test_momentum_skips_the_signal_month_and_does_not_read_the_future():
    ends = [_month_end(2019, month) for month in range(1, 13)] + [_month_end(2020, month) for month in range(1, 3)]
    close = np.full(len(ends), 10.0)
    close[-2] = 20.0  # month t-1, inside the formation window
    close[-1] = 100.0  # signal month, must not enter the ratio
    prep = prepare_tapes({"AAA3": _tape(ends, close)})["AAA3"]
    anchors = {(date.fromordinal(o).year, date.fromordinal(o).month): o for o in ends}
    signal = date.fromordinal(ends[-1])
    mom = momentum_12_1(prep, anchors, signal.year, signal.month)
    assert mom == pytest.approx(1.0)


def test_quality_is_point_in_time_and_skips_financials():
    old = BsPoint(_ord(2018, 12, 31), _ord(2019, 3, 1), 10, 4, 3, 5, assets=20, equity=8, cash=2, debt_st=1, debt_lt=2)
    new = BsPoint(_ord(2019, 12, 31), _ord(2020, 3, 20), 10, 4, 3, 5, assets=20, equity=80, cash=2, debt_st=1, debt_lt=2)
    earn = [EarnRow(_ord(2018, 1, 1), _ord(2018, 12, 31), _ord(2019, 3, 1), 4, ebit=6, ebt=5, revenue=40)]
    company = Company("00", "ALVO", "Têxtil", "ATIVO", [old, new], [], [], earn, [], [])
    asof = _ord(2020, 3, 1)
    parts = quality_components(company, asof)
    assert parts["roe"] == pytest.approx(4 / 8)
    assert "roic" in parts and "margin" in parts and "equity_ratio" in parts
    later = quality_components(company, _ord(2020, 3, 20))
    assert later["roe"] == pytest.approx(4 / 80)
    bank = Company("01", "BANCO", "Bancos", "ATIVO", [old], [], [], earn, [], [])
    assert quality_components(bank, asof) == {}


def test_low_vol_ranks_the_quiet_name_higher_and_liquidity_drops_the_thin_one():
    sessions = []
    day = date(2018, 1, 2)
    while len(sessions) < 160:
        if day.weekday() < 5:
            sessions.append(day.toordinal())
        day += timedelta(days=1)
    quiet = np.full(len(sessions), 10.0)
    wild = np.array([10.0 if i % 2 == 0 else 12.0 for i in range(len(sessions))])
    companies = [
        Company("q", "QUIET", "Têxtil", "ATIVO", [], [], [], [], [], [("QUIET3", sessions[0], None)]),
        Company("w", "WILD", "Têxtil", "ATIVO", [], [], [], [], [], [("WILD3", sessions[0], None)]),
        Company("t", "THIN", "Têxtil", "ATIVO", [], [], [], [], [], [("THIN3", sessions[0], None)]),
        Company("d", "DEAD", "Têxtil", "CANCELADA", [], [], [], [], [], [("DEAD3", sessions[0], sessions[5])]),
    ]
    tapes = {
        "QUIET3": _tape(sessions, quiet),
        "WILD3": _tape(sessions, wild),
        "THIN3": _tape(sessions, quiet, qty=100.0),
        "DEAD3": _tape(sessions, quiet),
    }
    prepared = prepare_tapes(tapes)
    # The signal needs a 12-month anchor in the calendar, so hand the candidates
    # a session list whose month-ends include that history by using the sessions
    # themselves as the only calendar. Momentum will be missing; vol will not.
    cands = build_candidates(companies, prepared, sessions, [sessions[-1]])[sessions[-1]]
    tickers = {c.ticker for c in cands}
    assert "QUIET3" in tickers and "WILD3" in tickers
    assert "THIN3" not in tickers
    assert "DEAD3" not in tickers
    assert max(c.adv_brl for c in cands) >= LIQUIDITY_ADV_BRL
    scores = score_factor(cands, "low_vol")
    assert scores["QUIET3"] > scores["WILD3"]


def test_top_quintile_stays_in_cash_below_25_names():
    small = {f"T{i:02d}": float(i) for i in range(24)}
    assert top_quintile(small) == []
    large = {f"T{i:02d}": float(i) for i in range(25)}
    held = top_quintile(large)
    assert held == [f"T{i:02d}" for i in range(24, 19, -1)]
    assert len(held) == 5


def test_composite_needs_all_three_legs():
    cands = [
        Candidate("a", "AAA3", 2e6, False, 0.2, 0.1, {"roe": 0.1, "equity_ratio": 0.5}),
        Candidate("b", "BBB3", 2e6, False, None, 0.1, {"roe": 0.2, "equity_ratio": 0.6}),
        Candidate("c", "CCC3", 2e6, True, 0.9, 0.05, {}),
    ]
    scores = score_factor(cands, "composite")
    assert list(scores) == ["AAA3"]
    assert "BBB3" not in scores
    assert "CCC3" not in scores


def test_choose_specification_ignores_out_of_sample_numbers():
    rows = [
        {
            "factor": "momentum_12_1",
            "frequency": "monthly",
            "design_sharpe": 0.2,
            "design_cagr": 0.01,
            "design_turnover": 1.0,
            "n_design": 40,
            "oos_sharpe": 9.0,
        },
        {
            "factor": "low_vol",
            "frequency": "quarterly",
            "design_sharpe": 0.8,
            "design_cagr": 0.02,
            "design_turnover": 0.4,
            "n_design": 40,
            "oos_sharpe": -2.0,
        },
    ]
    chosen = choose_specification(rows)
    assert chosen is not None
    assert chosen["factor"] == "low_vol"
    assert choose_specification([{**rows[1], "n_design": 12}]) is None


def test_grid_is_fixed_and_the_split_is_precommitted():
    grid = production_grid()
    assert len(grid) == 24
    assert {row["factor"] for row in grid} == {"momentum_12_1", "quality", "low_vol", "composite"}
    assert {row["frequency"] for row in grid} == {"monthly", "quarterly"}
    assert {row["aum"] for row in grid} == {100_000.0, 1_000_000.0, 10_000_000.0}
    assert sum(row["selection"] for row in grid) == 8
    assert all(row["aum"] == SELECTION_AUM for row in grid if row["selection"])
    assert DESIGN_END == date(2018, 12, 31)
    assert EVAL_START == date(2019, 1, 1)
    assert FAMILY_ID == "b3_long_horizon_factors"
    assert long_horizon.ELIGIBLE_FOR_LIVE_TRADING is False


def test_signal_book_uses_only_the_formation_window():
    # Fourteen month-ends. One name doubles in the formation window. Another
    # doubles only in the signal month and must not be preferred for that.
    ends = [_month_end(2018, m) for m in range(1, 13)] + [_month_end(2019, m) for m in range(1, 3)]
    # Business days between the first and last month-end, so ADV has a window.
    sessions = []
    day = date.fromordinal(ends[0])
    while day.toordinal() <= ends[-1]:
        if day.weekday() < 5:
            sessions.append(day.toordinal())
        day += timedelta(days=1)
    prices = {ticker: np.full(len(sessions), 10.0) for ticker in [f"N{i:02d}3" for i in range(25)]}
    # Map session -> index
    index = {ordinal: i for i, ordinal in enumerate(sessions)}
    prices["N00 3".replace(" ", "")][index[ends[-2]]] = 20.0
    prices["N24 3".replace(" ", "")][index[ends[-1]]] = 80.0
    companies = []
    tapes = {}
    for i in range(25):
        ticker = f"N{i:02d}3"
        companies.append(Company(str(i), ticker, "Têxtil", "ATIVO", [], [], [], [], [], [(ticker, sessions[0], None)]))
        tapes[ticker] = _tape(sessions, prices[ticker])
    signal = ends[-1]
    cands = build_candidates(companies, prepare_tapes(tapes), sessions, [signal])
    book = signal_book(cands, [signal], "momentum_12_1")
    held = {row.ticker for row in book[signal]}
    assert "N003" in held
    assert "N243" not in held
    assert len(held) == 5


def test_cdi_percent_is_divided_by_100():
    text = '[{"data":"02/01/2024","valor":"0.043739"},{"data":"03/01/2024","valor":"0.040000"}]'
    ords, rates = parse_sgs_cdi(text)
    assert rates[0] == pytest.approx(0.00043739)
    assert cdi_growth(ords, rates, int(ords[0]) - 1, int(ords[-1])) == pytest.approx((1 + rates[0]) * (1 + rates[1]))


def test_assemble_keeps_quality_fields_used_by_the_sleeve():
    end = _ord(2023, 12, 31)
    start = _ord(2023, 1, 1)
    received = _ord(2024, 3, 1)
    companies = assemble_companies(
        [("00", "ALVO", "Têxtil", "ATIVO")],
        {},
        [],
        {
            True: {
                ("00", received, end): {
                    "ca": 10,
                    "cl": 4,
                    "ltl": 3,
                    "capital": 5,
                    "assets": 20,
                    "equity": 8,
                    "cash": 2,
                    "debt_st": 1,
                    "debt_lt": 2,
                }
            },
            False: {},
        },
        {True: {("00", received, start, end): {"3.11": 4, "3.05": 6, "3.01": 30, "3.07": 5}}, False: {}},
        [],
    )
    point = companies[0].bs_con[0]
    assert point.equity == 8 and point.assets == 20 and point.cash == 2
    row = companies[0].er_con[0]
    assert row.ebit == 6 and row.revenue == 30 and row.ebt == 5
    text = (
        "CNPJ_CIA;DT_REFER;VERSAO;ESCALA_MOEDA;ORDEM_EXERC;DT_INI_EXERC;DT_FIM_EXERC;CD_CONTA;VL_CONTA\n"
        "00;2023-12-31;1;MIL;ÚLTIMO;2023-01-01;2023-12-31;3.05;1.5\n"
        "00;2023-12-31;1;MIL;ÚLTIMO;2023-01-01;2023-12-31;1;20\n"
    )
    parsed = parse_statement(text, True)
    codes = {item[5]: item[6] for item in parsed}
    assert codes["3.05"] == pytest.approx(1500)
    assert codes["1"] == pytest.approx(20_000)


def test_modules_do_not_open_the_network():
    source = inspect.getsource(long_horizon) + inspect.getsource(net_net_io)
    for banned in ("urllib", "requests", "httpx", "socket", "urlopen"):
        assert banned not in source

