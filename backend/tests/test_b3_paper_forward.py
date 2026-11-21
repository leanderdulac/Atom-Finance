"""Offline tests for the B3 forward paper books. No network."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.b3_paper_forward import router
from app.models.b3_paper_forward import (
    A_AUM,
    B_ADV_FLOOR,
    B_AUM,
    B_MIN_NAMES,
    B_REF_FULL_CAGR,
    B_REF_OOS_CAGR,
    B_REF_SHARPE,
    BOVA_TICKER,
    ENTRY_SESSION,
    SIGNAL_SESSION,
    Company,
    LedgerIntegrityError,
    LedgerTimeError,
    Tape,
    Target,
    _come_cotas,
    _contribute_cdi,
    _empty_cdi,
    build_monthly_report,
    combined_multiplier,
    commit_mark,
    file_sha256,
    initialize,
    load_book,
    outside_bova_band,
    paper_root,
    preregistration_document,
    read_entries,
    redeem_cdi_fifo,
    regressive_ir_rate,
    select_small_book,
    step_portfolio_b,
    tracking_vs_backtest,
    verify_ledger,
    write_preregistration,
)
from app.models.equal_weight import build_signal_book
from app.models.equal_weight_io import CashEvent, Listing
from app.models.net_net import FINANCIAL_SETORES, SharePoint

ROOT = Path(__file__).resolve().parents[2]


def _cdi_value(sleeve: dict) -> float:
    from app.models.b3_paper_forward import _cdi_value as value

    return value(sleeve)


def _tape(days: list[date], close: float | list[float], *, vol: float = 1_000_000.0, qty: float = 100_000.0) -> Tape:
    prices = close if isinstance(close, list) else [close] * len(days)
    ords = np.array([day.toordinal() for day in days], dtype=np.int64)
    px = np.array(prices, dtype=np.float64)
    return Tape(
        ords,
        px,
        px * 0.999,
        px * 1.001,
        np.full(len(days), qty),
        np.full(len(days), vol),
        np.ones(len(days)),
    )


def _history(end: date, n: int = 30) -> list[date]:
    return [date.fromordinal(end.toordinal() - (n - 1 - offset)) for offset in range(n)]


def _cash_book() -> dict:
    return {"signal_date": SIGNAL_SESSION.isoformat(), "names": [], "n": 0, "cash": True, "weight": 0.0}


def _boot(root: Path, book: dict | None = None) -> None:
    write_preregistration(root / "b3-paper-preregistration.json", book or _cash_book())
    initialize(root, timestamp="2026-11-21T12:00:00Z")


def _bova_days(marks: list[date], price_on) -> dict[str, Tape]:
    history = _history(marks[0], 25)
    days = sorted(set(history + list(marks)))
    return {BOVA_TICKER: _tape(days, [price_on(day) for day in days])}


def _mark(root: Path, session: date, tapes: dict[str, Tape], *, rate: float = 0.0, ibov: float = 100_000.0, today: date | None = None):
    return commit_mark(
        root,
        session,
        tapes,
        rate,
        ibov,
        None,
        None,
        None,
        today=today or session,
        timestamp=f"{session.isoformat()}T22:00:00Z",
    )


def test_regressive_table_and_come_cotas_are_explicit():
    assert regressive_ir_rate(0) == 0.225
    assert regressive_ir_rate(180) == 0.225
    assert regressive_ir_rate(181) == 0.20
    assert regressive_ir_rate(360) == 0.20
    assert regressive_ir_rate(361) == 0.175
    assert regressive_ir_rate(720) == 0.175
    assert regressive_ir_rate(721) == 0.15
    sleeve = {"cdi": _empty_cdi(), "come_cotas_paid": 0.0, "cdi_statutory_realized": 0.0, "cdi_complementary_paid": 0.0}
    _contribute_cdi(sleeve, 1000.0, date(2026, 11, 23))
    sleeve["cdi"]["cota"] = 1.1
    paid = _come_cotas(sleeve)
    assert paid == pytest.approx(15.0)
    assert _cdi_value(sleeve) == pytest.approx(1085.0)
    redeemed = redeem_cdi_fifo(sleeve, 10_000.0, date(2026, 11, 24))
    assert redeemed["statutory"] == pytest.approx(22.5)
    assert redeemed["complementary"] == pytest.approx(7.5)
    assert redeemed["net"] == pytest.approx(1077.5)


def test_come_cotas_waits_for_the_next_month_and_uses_the_pre_accrual_value(tmp_path: Path):
    _boot(tmp_path)
    days = [date(2026, 11, 23), date(2026, 11, 24), date(2026, 11, 25), date(2027, 6, 1)]
    tapes = _bova_days(days, lambda _day: 100.0)
    _mark(tmp_path, days[0], tapes)
    principal = load_book(tmp_path)["snapshot"]["a"]["cdi"]["lots"][0]["principal"]
    _mark(tmp_path, days[1], tapes, rate=0.04)
    after_accrual = load_book(tmp_path)["snapshot"]
    assert after_accrual["a"]["come_cotas_paid"] == pytest.approx(0.0)
    assert after_accrual["a"]["cdi"]["cota"] == pytest.approx(1.04)
    _mark(tmp_path, days[2], tapes, rate=0.0)
    assert load_book(tmp_path)["snapshot"]["a"]["come_cotas_paid"] == pytest.approx(0.0)
    _mark(tmp_path, days[3], tapes, rate=0.0)
    paid = load_book(tmp_path)["snapshot"]["a"]["come_cotas_paid"]
    assert paid == pytest.approx(0.15 * principal * 0.04)
    assert load_book(tmp_path)["snapshot"]["a"]["bova_fee_charged"] == 0.0


def test_band_is_five_points_and_does_not_trade_inside_it(tmp_path: Path):
    _boot(tmp_path)
    marks = [date(2026, 11, 23), date(2026, 11, 24), date(2026, 11, 25)]
    tapes = _bova_days(marks, lambda _day: 100.0)
    _mark(tmp_path, marks[0], tapes)
    opened = load_book(tmp_path)["snapshot"]["a"]["bova_shares"]
    assert opened > 0
    assert load_book(tmp_path)["snapshot"]["a"]["bova_fee_charged"] == 0.0
    _mark(tmp_path, marks[1], tapes)
    assert load_book(tmp_path)["snapshot"]["a"]["bova_shares"] == pytest.approx(opened)
    assert load_book(tmp_path)["snapshot"]["pending_a_rebalance"] is False
    _mark(tmp_path, marks[2], tapes)
    assert load_book(tmp_path)["snapshot"]["a"]["bova_shares"] == pytest.approx(opened)
    point = load_book(tmp_path)["snapshot"]["curve"][-1]
    assert outside_bova_band(point["a_bova_weight"]) is False
    assert point["combined_multiplier"] == pytest.approx(combined_multiplier(point["a_equity"], point["b_equity"]))
    embedded = load_book(tmp_path)["snapshot"]["a"]["bova_fee_embedded"]
    assert embedded >= 0.0
    # The close is already net of the ETF fee, so the mark does not subtract it again.
    assert point["a_equity"] == pytest.approx(point["a_equity"] + embedded - embedded)


def test_band_breach_fills_on_the_next_close_and_the_annual_date_does_not_force_a_trade(tmp_path: Path):
    _boot(tmp_path)
    prices = {date(2026, 11, 23): 100.0, date(2026, 11, 24): 200.0, date(2026, 11, 25): 200.0}
    tapes = _bova_days(list(prices), lambda day: prices.get(day, 100.0))
    _mark(tmp_path, date(2026, 11, 23), tapes)
    opened = load_book(tmp_path)["snapshot"]["a"]["bova_shares"]
    _mark(tmp_path, date(2026, 11, 24), tapes)
    breached = load_book(tmp_path)["snapshot"]
    assert breached["a"]["bova_shares"] == pytest.approx(opened)
    assert breached["pending_a_rebalance"] is True
    assert outside_bova_band(breached["curve"][-1]["a_bova_weight"]) is True
    _mark(tmp_path, date(2026, 11, 25), tapes)
    repaired = load_book(tmp_path)["snapshot"]
    assert repaired["a"]["bova_shares"] < opened
    assert outside_bova_band(repaired["curve"][-1]["a_bova_weight"]) is False

    annual_root = tmp_path / "annual"
    annual_root.mkdir()
    _boot(annual_root)
    annual_days = [date(2026, 11, 23), date(2027, 11, 23), date(2027, 11, 24)]
    annual_tapes = _bova_days(annual_days, lambda _day: 100.0)
    _mark(annual_root, annual_days[0], annual_tapes)
    shares = load_book(annual_root)["snapshot"]["a"]["bova_shares"]
    result = _mark(annual_root, annual_days[1], annual_tapes)
    review = result["notes"]["annual_review"]
    assert review["year"] == 2027
    assert review["forced_trade"] is False
    assert review["outside_band"] is False
    _mark(annual_root, annual_days[2], annual_tapes)
    assert load_book(annual_root)["snapshot"]["a"]["bova_shares"] == pytest.approx(shares)


def test_portfolio_b_uses_the_locked_selector_and_resizes_without_a_round_trip():
    companies = []
    listings = []
    tapes = {}
    start = date(2026, 10, 1)
    days = [date.fromordinal(start.toordinal() + offset) for offset in range(30)]
    asof = days[-1]
    for index in range(60):
        cnpj = f"{index:014d}"
        ticker = f"A{index:03d}3"
        setor = "Bancos" if index < 3 else "Construção"
        shares = [] if index == 3 else [SharePoint(asof.toordinal(), asof.toordinal(), 1_000_000.0 * (index + 1), 0.0, 1.0, 0.0)]
        companies.append(Company(cnpj, ticker, setor, "ATIVO", [], [], shares, [], [], []))
        listings.append(Listing(cnpj, ticker, days[0].toordinal(), None, "on"))
        volume = 1_000.0 if index in (4, 5) else 500_000.0
        tapes[ticker] = _tape(days, 10.0, vol=volume, qty=volume / 10.0)
    direct = build_signal_book(companies, listings, tapes, [asof.toordinal()], "small", B_ADV_FLOOR, min_names=B_MIN_NAMES)
    selected = select_small_book(companies, listings, tapes, asof)
    direct_names = [row.ticker for row in direct[asof.toordinal()]]
    assert [row["ticker"] for row in selected["names"]] == sorted(direct_names)
    assert selected["n"] >= B_MIN_NAMES
    assert selected["cash"] is False
    assert all(row["adv_brl"] >= B_ADV_FLOOR for row in selected["names"])
    assert all(abs(row["weight"] - 1.0 / selected["n"]) < 1e-12 for row in selected["names"])
    financial = {f"A{index:03d}3" for index in range(3)}
    assert financial.isdisjoint({row["ticker"] for row in selected["names"]})
    assert "Bancos" in FINANCIAL_SETORES

    sleeve = {
        "net_cash": 0.0,
        "gross_cash": 0.0,
        "net_positions": [
            {"ticker": "AAA3", "cnpj": "1", "shares": 10.0, "entry_px": 10.0, "entry_ord": 1},
            {"ticker": "BBB3", "cnpj": "2", "shares": 10.0, "entry_px": 10.0, "entry_ord": 1},
        ],
        "gross_positions": [
            {"ticker": "AAA3", "cnpj": "1", "shares": 10.0, "entry_px": 10.0, "entry_ord": 1},
            {"ticker": "BBB3", "cnpj": "2", "shares": 10.0, "entry_px": 10.0, "entry_ord": 1},
        ],
        "dividend_gross": 0.0,
        "dividend_withheld": 0.0,
        "dividend_net": 0.0,
        "stale_sells": 0,
        "worthless_exits": 0,
        "rebalance_turnover": 0.0,
        "costs": {"fee": 0.0, "half_spread": 0.0, "slippage": 0.0, "n": 0.0, "n_capped": 0.0, "notional": 0.0},
        "last_target_weights": {"AAA3": 0.5, "BBB3": 0.5},
    }
    ordinal = date(2026, 11, 23).toordinal()
    history = [date.fromordinal(ordinal - 20 + offset) for offset in range(21)]
    book = {"AAA3": _tape(history, [10.0] * 20 + [30.0]), "BBB3": _tape(history, 10.0)}
    targets = [Target("1", "AAA3", 500_000.0, 10_000.0, 1.0), Target("2", "BBB3", 500_000.0, 10_000.0, 1.0)]
    result = step_portfolio_b(sleeve, book, ordinal, ordinal - 1, targets, None, count_turnover=True)
    assert result["fills"] == 2
    held = {row["ticker"]: row["shares"] for row in sleeve["net_positions"]}
    assert held["AAA3"] == pytest.approx(200.0 / 30.0, rel=0.02)
    assert held["BBB3"] > 10.0


def test_dividends_withholding_and_stale_exit_follow_the_locked_rule():
    ordinal = date(2026, 11, 23).toordinal()
    history = [date.fromordinal(ordinal - 5 + offset) for offset in range(6)]
    tape = _tape(history, 10.0)

    def sleeve(shares: float = 10.0) -> dict:
        return {
            "net_cash": 0.0,
            "gross_cash": 0.0,
            "net_positions": [{"ticker": "AAA3", "cnpj": "1", "shares": shares, "entry_px": 10.0, "entry_ord": 1}],
            "gross_positions": [{"ticker": "AAA3", "cnpj": "1", "shares": shares, "entry_px": 10.0, "entry_ord": 1}],
            "dividend_gross": 0.0,
            "dividend_withheld": 0.0,
            "dividend_net": 0.0,
            "stale_sells": 0,
            "worthless_exits": 0,
            "rebalance_turnover": 0.0,
            "costs": {"fee": 0.0, "half_spread": 0.0, "slippage": 0.0, "n": 0.0, "n_capped": 0.0, "notional": 0.0},
            "last_target_weights": {},
        }

    events = {
        "AAA3": [
            CashEvent(ordinal, 1.0, "dividendo"),
            CashEvent(ordinal, 1.0, "jcp"),
            CashEvent(ordinal, 1.0, "unknown"),
        ]
    }
    book = sleeve()
    step_portfolio_b(book, {"AAA3": tape}, ordinal, ordinal - 1, None, events, count_turnover=False)
    assert book["dividend_gross"] == pytest.approx(30.0)
    assert book["dividend_withheld"] == pytest.approx(3.0)
    assert book["dividend_net"] == pytest.approx(27.0)
    assert book["net_cash"] == pytest.approx(27.0)

    huge = {"AAA3": [CashEvent(ordinal, 1000.0, "dividendo")]}
    dropped = sleeve()
    step_portfolio_b(dropped, {"AAA3": tape}, ordinal, ordinal - 1, None, huge, count_turnover=False)
    assert dropped["dividend_net"] == pytest.approx(0.0)

    stale = sleeve()
    old = [date.fromordinal(ordinal - 20 + offset) for offset in range(10)]
    step_portfolio_b(stale, {"AAA3": _tape(old, 10.0)}, ordinal, None, None, None, count_turnover=False)
    assert stale["net_positions"] == []
    assert stale["stale_sells"] == 1
    assert stale["net_cash"] > 0

    held = sleeve()
    step_portfolio_b(held, {"AAA3": _tape([date.fromordinal(ordinal - 10)], 10.0)}, ordinal, None, None, None, count_turnover=False)
    assert held["net_positions"]
    assert held["stale_sells"] == 0


def test_future_close_cannot_enter_the_fill_and_the_chain_rejects_tampering(tmp_path: Path):
    _boot(tmp_path)
    session = date(2026, 11, 23)
    later = date(2026, 11, 24)
    days = _history(later, 30)
    prices = [100.0 if day <= session else 999.0 for day in days]
    tapes = {BOVA_TICKER: _tape(days, prices)}
    _mark(tmp_path, session, tapes, today=session)
    snap = load_book(tmp_path)["snapshot"]
    assert snap["curve"][-1]["a_bova_mv"] == pytest.approx(snap["a"]["bova_shares"] * 100.0, rel=0.02)
    assert snap["curve"][-1]["a_bova_mv"] < 400_000
    with pytest.raises(LedgerTimeError):
        _mark(tmp_path, session, tapes, today=later)
    with pytest.raises(LedgerTimeError):
        _mark(tmp_path, date(2026, 11, 22), tapes, today=later)
    with pytest.raises(LedgerTimeError):
        _mark(tmp_path, later, tapes, today=session)

    ledger = tmp_path / "b3_paper" / "ledger.jsonl"
    rows = ledger.read_text(encoding="utf-8").splitlines()
    forged = json.loads(rows[0])
    forged["body"]["state"]["a"]["idle_cash"] = 1.0
    rows[0] = json.dumps(forged)
    ledger.write_text("\n".join(rows) + "\n", encoding="utf-8")
    with pytest.raises(LedgerIntegrityError):
        load_book(tmp_path)


def test_tracking_interval_and_monthly_report(tmp_path: Path):
    mu = (1.0 + B_REF_OOS_CAGR) ** (1.0 / 12.0) - 1.0
    flat = tracking_vs_backtest([mu, mu, mu])
    assert flat["z_oos"] == pytest.approx(0.0, abs=1e-9)
    assert flat["outside_95"] is False
    hot = tracking_vs_backtest([0.5, 0.5, 0.5])
    assert hot["z_oos"] > 2
    assert hot["outside_95"] is True
    assert tracking_vs_backtest([])["z_oos"] is None
    _boot(tmp_path)
    session = date(2026, 11, 23)
    _mark(tmp_path, session, _bova_days([session], lambda _day: 100.0))
    report = build_monthly_report(load_book(tmp_path)["snapshot"], "2026-11")
    assert report["eligible_for_live_trading"] is False
    assert report["returns"]["combined_90_10"] == pytest.approx(0.9 * report["returns"]["A"] + 0.1 * report["returns"]["B"])
    assert set(report["returns"]) == {"A", "B", "combined_90_10", "cdi_gross", "ibovespa_total_return"}
    assert report["tax"]["ir_paid_brl"] >= 0.0
    assert "ir_gross_brl" in report["tax"]
    assert "ir_provision_brl" in report["tax"]


def test_read_only_api(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("ATOM_B3_PAPER_ROOT", str(tmp_path))
    assert paper_root() == tmp_path
    _boot(tmp_path)
    app = FastAPI()
    app.include_router(router, prefix="/api/b3-paper")
    client = TestClient(app)
    state = client.get("/api/b3-paper/state")
    assert state.status_code == 200
    body = state.json()
    assert body["eligible_for_live_trading"] is False
    assert body["pending_inception"] is True
    assert body["entry_session"] == ENTRY_SESSION.isoformat()
    ledger = client.get("/api/b3-paper/ledger")
    assert ledger.status_code == 200
    assert ledger.json()["verified"] is True
    assert ledger.json()["count"] == 2
    frozen = client.get("/api/b3-paper/preregistration")
    assert frozen.status_code == 200
    assert frozen.json()["sha256"] == file_sha256(tmp_path / "b3-paper-preregistration.json")
    assert frozen.json()["preregistration"]["eligible_for_live_trading"] is False
    missing = client.get("/api/b3-paper/reports/monthly", params={"month": "2026-11"})
    assert missing.status_code == 404
    session = date(2026, 11, 23)
    _mark(tmp_path, session, _bova_days([session], lambda _day: 100.0))
    report = client.get("/api/b3-paper/reports/monthly", params={"month": "2026-11"})
    assert report.status_code == 200
    assert report.json()["eligible_for_live_trading"] is False
    listed = client.get("/api/b3-paper/reports/monthly")
    assert listed.json()["months"] == ["2026-11"]
    composition = client.get("/api/b3-paper/composition")
    assert composition.status_code == 200
    assert composition.json()["positions_a"]["bova_shares"] > 0

    rows = read_entries(tmp_path)
    rows[1]["body"]["planned_entry"] = "2020-01-01"
    (tmp_path / "b3_paper" / "ledger.jsonl").write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
    assert client.get("/api/b3-paper/state").status_code == 409
    with pytest.raises(LedgerIntegrityError):
        verify_ledger(rows, file_sha256(tmp_path / "b3-paper-preregistration.json"))


def test_constants_match_the_frozen_rule_text():
    document = preregistration_document(_cash_book())
    assert document["eligible_for_live_trading"] is False
    assert document["portfolio_a"]["weights"] == {"cdi_proxy": 0.70, "BOVA11": 0.30}
    assert document["portfolio_a"]["band"]["low"] == 0.25
    assert document["portfolio_a"]["band"]["high"] == 0.35
    assert document["portfolio_a"]["bova11_admin_fee"]["charged_on_top_of_close"] == 0
    assert document["portfolio_b"]["adv_floor_brl"] == B_ADV_FLOOR
    assert document["portfolio_b"]["min_names_else_cash"] == B_MIN_NAMES
    assert document["combined"]["weights"] == {"A": 0.90, "B": 0.10}
    assert document["tracking"]["oos_net_cagr"] == B_REF_OOS_CAGR
    assert document["tracking"]["full_sample_net_cagr"] == B_REF_FULL_CAGR
    assert document["tracking"]["sharpe"] == B_REF_SHARPE
    assert document["evaluation"]["horizons"][0]["on_or_before"] == "2027-05-23"
    assert document["evaluation"]["horizons"][1]["on_or_before"] == "2027-11-23"
    assert A_AUM == 1_000_000.0
    assert B_AUM == 100_000.0


def test_committed_book_is_frozen_and_chain_verifies():
    path = ROOT / "docs" / "reports" / "b3-paper-preregistration.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    book = document["portfolio_b_initial_target"]
    names = book["names"]
    assert document["frozen_on"] < ENTRY_SESSION.isoformat()
    assert document["signal_session"] == "2026-11-19"
    assert document["entry_session"] == "2026-11-23"
    assert document["eligible_for_live_trading"] is False
    assert book["n"] == len(names) >= B_MIN_NAMES
    assert book["cash"] is False
    assert all(row["adv_brl"] >= B_ADV_FLOOR for row in names)
    assert all(abs(row["weight"] - 1.0 / len(names)) < 1e-9 for row in names)
    assert abs(sum(row["weight"] for row in names) - 1.0) < 1e-8
    assert len({row["ticker"] for row in names}) == len(names)
    loaded = load_book(ROOT / "docs" / "reports")
    assert loaded["snapshot"]["eligible_for_live_trading"] is False
    assert loaded["snapshot"]["pending_inception"] is True
    assert len(loaded["snapshot"]["frozen_b_targets"]) == len(names)
    entries = read_entries(ROOT / "docs" / "reports")
    assert entries[0]["kind"] == "genesis"
    assert entries[0]["body"]["preregistration_sha256"] == file_sha256(path)
    assert entries[1]["kind"] == "target"
    assert entries[1]["session_date"] == "2026-11-19"
    assert [row["ticker"] for row in entries[1]["body"]["portfolio_b"]["names"]] == [row["ticker"] for row in names]
