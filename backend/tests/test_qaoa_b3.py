"""QAOA B3 phase 1. Synthetic tapes only. No network and no orders."""

from __future__ import annotations

import json
from datetime import date
from itertools import combinations
from pathlib import Path

import numpy as np
import pytest

from app.models.afml.trials import TrialRegistry
from app.models.equal_weight import SELECTION_AUM, simulate_book
from app.models.qaoa_b3 import (
    ADV_FLOOR,
    ELIGIBLE_FOR_LIVE_TRADING,
    EMBARGO_SESSIONS,
    EVAL_START,
    FAMILY_ID,
    GENERATED_SOLVERS,
    K_MAX,
    K_MIN,
    LAMBDA_GRID,
    PUBLISHED_FIRST_SIGNAL,
    RANDOM_SEEDS,
    Selection,
    _book_from_group,
    build_snapshots,
    canonical_solver,
    choose_rule,
    cover_dates,
    generate_selections,
    holdout_points,
    judge,
    objective_score,
    prior_ledger,
    published_equal_weight_trials,
    quarter_signals,
    quote_cost,
    run_study,
    schema_fixture_world,
    selection_from_mapping,
    solve_milp,
    validate_selection,
)
from app.models.qaoa_b3_io import read_table, universe_from_rows, write_holdout, write_snapshot
from app.models.rejected_net_net import rejected_ledger_count

_REPO = Path(__file__).resolve().parents[2]
_NEW_SOURCES = (
    _REPO / "backend" / "app" / "models" / "qaoa_b3.py",
    _REPO / "backend" / "app" / "models" / "qaoa_b3_io.py",
    _REPO / "scripts" / "export_qaoa_b3_snapshots.py",
    _REPO / "scripts" / "validate_qaoa_b3_selections.py",
    _REPO / "docs" / "QAOA-B3-PHASE1.md",
)


@pytest.fixture(scope="module")
def world() -> dict:
    return schema_fixture_world()


@pytest.fixture(scope="module")
def built(world: dict):
    book, taxed, snaps = build_snapshots(
        world["companies"], world["listings"], world["tapes"], world["sessions"], world["events"]
    )
    return book, taxed, snaps


def test_constants_match_the_published_sleeve():
    report = json.loads((_REPO / "docs" / "reports" / "equal-weight-b3.json").read_text(encoding="utf-8"))
    selected = report["oos_split"]["selected"]
    assert selected["universe"] == "small"
    assert selected["adv_floor"] == ADV_FLOOR
    assert selected["frequency"] == "quarterly"
    assert selected["aum_brl"] == SELECTION_AUM
    assert report["n_trials"] == 55
    assert published_equal_weight_trials() == 55
    assert rejected_ledger_count() == 32
    assert K_MIN == 15 and K_MAX == 20
    assert LAMBDA_GRID == (0.5, 1.0, 2.0, 5.0)
    assert ELIGIBLE_FOR_LIVE_TRADING is False
    assert "qaoa_aer" not in GENERATED_SOLVERS


def test_no_rebalance_before_the_published_first_signal():
    days = [PUBLISHED_FIRST_SIGNAL.toordinal()]
    for year in (2010, 2011, 2012):
        for month, last in ((3, 31), (6, 30), (9, 30), (12, 31)):
            days.append(date(year, month, last).toordinal())
    signals = [date.fromordinal(day) for day in quarter_signals(sorted(set(days)))]
    assert signals
    assert all(day >= PUBLISHED_FIRST_SIGNAL for day in signals)
    assert date(2010, 12, 31) not in signals
    assert date(2012, 3, 31) not in signals
    assert date(2012, 5, 2) not in signals
    assert date(2012, 6, 30) in signals
    assert date(2012, 9, 30) in signals


def test_universe_is_the_locked_small_cap_rule(built):
    book, _taxed, snaps = built
    assert [snap.rebalance for snap in snaps] == [date(2012, 6, 30), date(2012, 9, 30)]
    rows = book[date(2012, 6, 30).toordinal()]
    tickers = {row.ticker for row in rows}
    assert len(rows) >= 15
    assert "BANK3" not in tickers
    assert "THIN3" not in tickers
    assert "TWIN3" not in tickers
    assert "S000" in tickers
    assert "S049" not in tickers
    assert all(row.adv_brl >= ADV_FLOOR for row in rows)
    assert snaps[0].cash is False


def test_snapshot_is_causal_and_the_embargo_is_out_of_mu(built):
    _book, _taxed, snaps = built
    snap = snaps[0]
    assert snap.rebalance == date(2012, 6, 30)
    assert snap.estimation_end == date(2012, 6, 25)
    assert (snap.rebalance_ordinal - snap.estimation_end_ordinal) == EMBARGO_SESSIONS
    s000 = next(name for name in snap.names if name.ticker == "S000")
    assert s000.mu == pytest.approx(0.0)
    signal_return = next(point for point in s000.returns if point.ordinal == snap.rebalance_ordinal)
    assert signal_return.value == pytest.approx(1.0)
    assert signal_return.in_mu_window is False
    assert signal_return.in_estimation is False
    assert all(point.ordinal <= snap.rebalance_ordinal for name in snap.names for point in name.returns)
    window = [point for point in s000.returns if point.in_mu_window]
    assert window
    assert max(point.ordinal for point in window) == snap.estimation_end_ordinal
    s001 = next(name for name in snap.names if name.ticker == "S001")
    dividend = next(point for point in s001.returns if point.ordinal == date(2012, 6, 11).toordinal())
    assert dividend.value == pytest.approx(0.085)
    assert dividend.in_mu_window is True
    s002 = next(name for name in snap.names if name.ticker == "S002")
    split = next(point for point in s002.returns if point.ordinal == date(2012, 6, 10).toordinal())
    assert split.value == pytest.approx(0.0)
    name = snap.names[0]
    recomputed = quote_cost(name.close, name.bid, name.ask, name.adv_brl, name.adv_shares, SELECTION_AUM, len(snap.names))
    assert recomputed["roundtrip_bps"] == pytest.approx(name.costs["aum_1m"]["roundtrip_bps"])
    assert name.costs["aum_100k"]["notional"] == pytest.approx(100_000.0 / len(snap.names))
    assert name.costs["aum_1m"]["notional"] == pytest.approx(SELECTION_AUM / len(snap.names))


def test_holdout_starts_after_the_signal_and_does_not_change_the_snapshot_hash(built, world):
    book, taxed, snaps = built
    snap = snaps[0]
    before = snap.snapshot_hash
    last, points = holdout_points(
        snap.rebalance_ordinal,
        snaps[1].rebalance_ordinal,
        world["sessions"],
        book[snap.rebalance_ordinal],
        world["tapes"],
        taxed,
    )
    assert last == snaps[1].rebalance_ordinal
    assert points
    assert all(ordinal > snap.rebalance_ordinal for _ticker, ordinal, _value in points)
    july2 = date(2012, 7, 2).toordinal()
    jump = [value for ticker, ordinal, value in points if ticker == "S000" and ordinal == july2]
    assert jump and jump[0] == pytest.approx(0.5)
    assert snap.snapshot_hash == before
    assert not any(point.ordinal == july2 for name in snap.names for point in name.returns)


def test_hash_tracks_the_payload_and_parquet_stays_causal(built, tmp_path: Path):
    _book, _taxed, snaps = built
    snap = snaps[0]
    path = write_snapshot(tmp_path, snap)
    rows = read_table(path)
    day, tickers, digest = universe_from_rows(rows)
    assert day == snap.rebalance
    assert tickers == set(snap.tickers)
    assert digest == snap.snapshot_hash
    body = json.loads((tmp_path / "2012-06-30.json").read_text(encoding="utf-8"))
    assert body["snapshot_hash"] == snap.snapshot_hash
    assert body["eligible_for_live_trading"] is False
    assert body["payload"]["sigma"]["tickers"] == list(snap.sigma_tickers)
    hold = write_holdout(tmp_path / "holdout", snap, snaps[1].rebalance, (("S000", date(2012, 7, 2).toordinal(), 0.5),))
    forward = read_table(hold)
    assert all(date.fromisoformat(row["session_date"]) > snap.rebalance for row in forward)
    assert all(row["purpose"] == "not_for_selection" for row in forward)
    assert forward[0]["selection_snapshot_hash"] == snap.snapshot_hash


def test_rejects_a_ticker_outside_the_universe_and_a_leaked_field(built):
    _book, _taxed, snaps = built
    universe = snaps[0].tickers
    picked = universe[:14] + ("NOPE3",)
    with pytest.raises(ValueError, match="outside"):
        validate_selection(Selection(snaps[0].rebalance, "milp_exact", 15, 1.0, None, tuple(sorted(picked))), universe)
    with pytest.raises(ValueError, match="held-out"):
        selection_from_mapping(
            {
                "rebalance_date": "2012-06-30",
                "solver": "sa",
                "K": 15,
                "lambda": 1,
                "p": None,
                "tickers": list(universe[:15]),
                "oos_sharpe": 3.0,
            }
        )
    leaked = Selection(
        snaps[0].rebalance,
        "qaoa_aer",
        15,
        1.0,
        1,
        universe[:15],
        meta=(("holdout_return", "1"),),
    )
    with pytest.raises(ValueError, match="held-out"):
        validate_selection(leaked, universe)
    with pytest.raises(ValueError, match="p must be 1 or 2"):
        validate_selection(
            Selection(snaps[0].rebalance, "qaoa_aer", 15, 0.5, 3, universe[:15]),
            universe,
        )
    ok = Selection(snaps[0].rebalance, "qaoa_aer", 15, 0.5, 2, tuple(sorted(universe[:15])))
    validate_selection(ok, universe)
    aliased = selection_from_mapping(
        {
            "rebalance_date": "2012-06-30",
            "solver": "equal_weight_universe",
            "K": len(universe),
            "lambda": None,
            "p": None,
            "tickers": list(universe),
        }
    )
    assert aliased.solver == "equal_weight37"
    assert canonical_solver("simulated_annealing") == "sa"
    assert canonical_solver("random_k") == "random_K"
    with pytest.raises(ValueError, match="universe size"):
        validate_selection(
            Selection(snaps[0].rebalance, "equal_weight37", 37, None, None, universe),
            universe,
        )


def test_full_universe_selection_reproduces_the_equal_weight_path(built, world):
    book, taxed, snaps = built
    selections = generate_selections(book, snaps, solvers=("equal_weight37",))
    groups = cover_dates(selections, [snap.rebalance for snap in snaps])
    group = groups[("equal_weight37", None, None, None, None)]
    by_ord = {snap.rebalance_ordinal: snap for snap in snaps}
    selected = _book_from_group(book, by_ord, group)
    direct = simulate_book(
        world["sessions"], world["tapes"], book, SELECTION_AUM, taxed, round_trip=False, exit_when_stale=True
    )
    via = simulate_book(
        world["sessions"], world["tapes"], selected, SELECTION_AUM, taxed, round_trip=False, exit_when_stale=True
    )
    assert via["net"] == pytest.approx(direct["net"])
    assert via["gross"] == pytest.approx(direct["gross"])
    assert via["eligible_for_live_trading"] is False
    june = date(2012, 6, 30).toordinal()
    assert direct["logs"][0]["signal"] == june
    assert direct["logs"][0]["trade"] == june + 1


def test_rule_choice_reads_the_design_window_only():
    weak = {
        "selection_candidate": True,
        "design_sharpe": 0.2,
        "design_cagr": 0.01,
        "design_turnover": 0.2,
        "n_design": 40,
        "k": 15,
        "lam": 1.0,
        "solver": "milp_exact",
        "p": None,
        "seed": None,
        "oos_sharpe": 4.0,
        "oos_cagr_net": 0.9,
    }
    strong = {
        "selection_candidate": True,
        "design_sharpe": 0.8,
        "design_cagr": 0.02,
        "design_turnover": 0.5,
        "n_design": 40,
        "k": 18,
        "lam": 2.0,
        "solver": "sa",
        "p": None,
        "seed": 7,
        "oos_sharpe": -1.0,
        "oos_cagr_net": -0.4,
    }
    short = dict(strong, n_design=12, design_sharpe=5.0)
    picked = choose_rule([weak, strong, short])
    assert picked is not None
    assert picked["solver"] == "sa"
    assert picked["design_sharpe"] == 0.8
    assert choose_rule([short]) is None
    baseline = dict(strong, selection_candidate=False, solver="equal_weight37", design_sharpe=3.0)
    assert choose_rule([baseline, weak])["solver"] == "milp_exact"


def test_decision_n_counts_prior_trials(tmp_path: Path):
    registry = tmp_path / "trials.sqlite"
    series = [0.02, -0.01, 0.015, 0.0, 0.01, -0.005] * 4
    with TrialRegistry(registry) as reg:
        reg.register(
            FAMILY_ID,
            {"solver": "equal_weight37", "role": "baseline"},
            returns=series,
            costs_included=True,
            periods_per_year=12,
        )
        priors = prior_ledger(reg)
        assert reg.count("b3_graham_net_net") == 32
    assert priors["family"] == 1
    assert priors["rejected_net_net"] == 32
    assert priors["equal_weight"] == 55
    assert priors["equal_weight_source"] == "published_report"
    assert priors["factor_accessible"] is False
    assert priors["n_decision"] == 1 + 32 + 55
    wide = judge(series, priors["n_decision"])
    narrow = judge(series, 2)
    assert wide is not None and narrow is not None
    assert wide["dsr"] < narrow["dsr"]
    assert wide["n_trials"] == 88


def test_milp_matches_a_complete_enumeration():
    mu = np.array([0.002, -0.001, 0.0015, 0.0004, -0.0008], dtype=np.float64)
    sigma = np.diag([0.0004, 0.0009, 0.0002, 0.0005, 0.0003])
    sigma[0, 1] = sigma[1, 0] = 0.0001
    cost = np.array([0.01, 0.002, 0.004, 0.003, 0.008], dtype=np.float64)
    best_score = -1e18
    best: tuple[int, ...] = ()
    for combo in combinations(range(5), 2):
        score = objective_score(mu, sigma, cost, combo, 1.0)
        if score > best_score:
            best_score = score
            best = combo
    picked = solve_milp(mu, sigma, cost, 2, 1.0)
    assert picked is not None
    assert objective_score(mu, sigma, cost, picked, 1.0) == pytest.approx(best_score)
    assert tuple(sorted(picked)) == tuple(sorted(best))


def test_random_k_is_deterministic_and_inside_the_universe(built):
    book, _taxed, snaps = built
    targets = book[snaps[0].rebalance_ordinal]
    first = generate_selections(book, snaps, solvers=("random_K",), k_values=(15,), random_seeds=RANDOM_SEEDS)
    second = generate_selections(book, snaps, solvers=("random_K",), k_values=(15,), random_seeds=RANDOM_SEEDS)
    assert [sel.tickers for sel in first] == [sel.tickers for sel in second]
    universe = {row.ticker for row in targets}
    june = [sel for sel in first if sel.rebalance == snaps[0].rebalance]
    assert {sel.seed for sel in june} == set(RANDOM_SEEDS)
    for sel in june:
        assert len(sel.tickers) == 15
        assert set(sel.tickers) <= universe
    assert june[0].tickers != june[1].tickers


def test_short_sample_registers_trials_and_stays_paper(world, tmp_path: Path):
    report = run_study(
        world["companies"],
        world["tapes"],
        world["sessions"],
        world["events"],
        np.asarray([], dtype=np.int64),
        np.asarray([], dtype=np.float64),
        tmp_path / "trials.sqlite",
        world["listings"],
        solvers=("equal_weight37", "equal_weight_k"),
        k_values=(15,),
        lambdas=(),
    )
    assert report["eligible_for_live_trading"] is False
    assert report["verdict"] == "inconclusivo"
    assert report["market_sample"] is True
    assert report["criterion_met"] is False
    assert report["awaiting_solver"] == ["qaoa_aer"]
    assert report["n_trials_decision"] == report["priors"]["family"] + 32 + 55
    assert report["priors"]["family"] >= 1
    assert all(row["eligible_for_live_trading"] is False for row in report["trials"])
    assert date.fromisoformat(report["rebalance_dates"][0]) >= PUBLISHED_FIRST_SIGNAL
    assert date.fromisoformat(report["rebalance_dates"][0]) < EVAL_START


def test_new_sources_do_not_name_forbidden_topics():
    banned = ("ollama", "macos", "macOS", "cloudflare", "gpu", "tunnel", "túnel")
    for path in _NEW_SOURCES:
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8").lower()
        for word in banned:
            assert word.lower() not in text, f"{word} in {path.name}"
