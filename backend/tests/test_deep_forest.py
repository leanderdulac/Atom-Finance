"""Causal cascade forest, layered GBDT, risk boxes, and the paper harness.

Prefix checks are bit-exact: future prices or future labels do not change a
past score. The live-trading flag stays false. No order is sent.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.api.harness import router
from app.core.client_mode import client_may_access
from app.core.limiter import limiter
from app.core.security import get_current_user
from app.harness.paper import ELIGIBLE_FOR_LIVE_TRADING as HARNESS_LIVE
from app.harness.runtime import HarnessRuntime
from app.harness.tree_study import (
    FAMILY,
    N_TRIALS,
    REGISTERED_TRIALS,
    prepare_book,
    price_path,
    run_benchmark,
    submit_study,
)
from app.models._causal import ELIGIBLE_FOR_LIVE_TRADING as DESK_LIVE
from app.models.deep_forest import (
    B3_SECTORS,
    TINY_CONFIG,
    CascadeDeepForest,
    CausalRidge,
    EnsembleConfig,
    MultiLayerGBDT,
    ResearchPanel,
    build_decision_frame,
    load_b3_research_panel,
    train_end_exclusive,
    walk_forward_predict,
)
from app.models.deep_forest import (
    ELIGIBLE_FOR_LIVE_TRADING as MODEL_LIVE,
)
from app.models.risk_box import (
    ELIGIBLE_FOR_LIVE_TRADING as BOX_LIVE,
)
from app.models.risk_box import (
    RiskBox,
    _cost_step,
    box_for_mode,
    constrain_weights,
    exposure_violations,
    neutral_book,
    scores_to_target,
    weights_from_scores,
)
from app.models.trading_costs import entry_allowed, leg_rate_bps
from tests.causal_bits import assert_causal_prefix, assert_same_bits, perturb

MUTATIONS = ("noise", "nan")


@dataclass
class _Path:
    score: np.ndarray
    weight: np.ndarray


def _prices(n: int = 150, assets: int = 4, seed: int = 7) -> np.ndarray:
    rng = np.random.default_rng(seed)
    shocks = rng.normal(0.0004, 0.01, size=(n, assets))
    return 50.0 * np.exp(np.cumsum(shocks, axis=0))


def _sectors(assets: int = 4) -> np.ndarray:
    return np.asarray(["A" if i % 2 == 0 else "B" for i in range(assets)])


def _panel(n: int = 150, assets: int = 4, seed: int = 7) -> ResearchPanel:
    prices = _prices(n, assets, seed)
    names = tuple(f"N{i}" for i in range(assets))
    sectors = tuple(str(s) for s in _sectors(assets))
    dates = tuple(f"2021-01-{i:03d}" for i in range(n))
    return ResearchPanel(names=names, sectors=sectors, dates=dates, prices=prices)


def _box() -> RiskBox:
    return RiskBox(
        mode="index_enhancement",
        name_cap=0.04,
        sector_cap=0.05,
        net_min=0.96,
        net_max=1.04,
        factor_cap=0.08,
        abs_name_cap=0.40,
        score_scale=0.02,
        commission_bps=5.0,
        slippage_bps=5.0,
        half_spread_bps=2.0,
    )


def test_live_trading_stays_false():
    assert MODEL_LIVE is False
    assert BOX_LIVE is False
    assert HARNESS_LIVE is False
    assert DESK_LIVE is False
    assert CascadeDeepForest().eligible_for_live_trading is False
    assert MultiLayerGBDT().eligible_for_live_trading is False
    assert CausalRidge().eligible_for_live_trading is False
    assert not client_may_access("/api/harness/studies/tree-ensemble")
    with pytest.raises(ValueError):
        EnsembleConfig(eligible_for_live_trading=True)
    with pytest.raises(ValueError):
        RiskBox(
            mode="market_neutral",
            name_cap=0.02,
            sector_cap=0.02,
            net_min=-0.02,
            net_max=0.02,
            factor_cap=0.05,
            abs_name_cap=0.02,
            eligible_for_live_trading=True,
        )


def test_b3_panel_is_the_committed_tape():
    panel = load_b3_research_panel()
    assert panel.names == tuple(B3_SECTORS)
    assert panel.sectors == tuple(B3_SECTORS[name] for name in panel.names)
    assert panel.prices.shape == (len(panel.dates), len(panel.names))
    assert panel.prices.shape[0] > 1000
    assert panel.eligible_for_live_trading is False
    assert len(set(panel.sectors)) >= 4


def test_features_do_not_use_the_next_price():
    prices = _prices()
    frame = build_decision_frame(prices, TINY_CONFIG)
    assert np.all(np.isfinite(frame.features))
    assert np.all(np.isfinite(frame.labels))
    changed = prices.copy()
    changed[-1] = prices[-1] * 1.4
    other = build_decision_frame(changed, TINY_CONFIG)
    assert_same_bits(frame.features, other.features)
    assert not np.allclose(frame.labels[-1], other.labels[-1])


@pytest.mark.parametrize("kind", MUTATIONS)
def test_feature_prefix_is_bit_exact(kind: str):
    prices = _prices()
    cut = 90
    base = build_decision_frame(prices, TINY_CONFIG)
    alt = build_decision_frame(perturb(prices, cut, kind), TINY_CONFIG)
    keep = base.index <= cut
    assert_same_bits(base.features[keep], alt.features[keep])
    labels = base.index <= cut - 1
    assert_same_bits(base.labels[labels], alt.labels[labels])


def test_train_cutoff_matches_the_harness_gap():
    assert train_end_exclusive(20, 1) == 18
    embargo = 1
    seen: list[tuple[int, int]] = []

    def fit_block(times, x_train, y_train, x_block):
        seen.append((int(np.max(x_train[:, 0])), int(np.min(x_block[:, 0]))))
        pred = np.zeros(len(x_block), dtype=np.float64)
        return pred, pred[:, None]

    n_time, n_asset = 48, 3
    features = np.zeros((n_time, n_asset, 2), dtype=np.float64)
    features[:, :, 0] = np.arange(n_time, dtype=np.float64)[:, None]
    labels = np.random.default_rng(0).normal(size=(n_time, n_asset))
    _pred, _rep, folds = walk_forward_predict(
        features,
        labels,
        config=TINY_CONFIG,
        represent_dim=1,
        fit_block=fit_block,
    )
    assert folds
    assert seen
    for train_end, test_start, fold_embargo in folds:
        assert fold_embargo == embargo
        assert train_end + fold_embargo < test_start
        assert test_start == train_end + fold_embargo + 1
    for max_train, min_block in seen:
        assert max_train <= min_block - embargo - 2


@pytest.mark.parametrize("kind", MUTATIONS)
@pytest.mark.parametrize("model", ("cascade_forest", "mgbdt"))
def test_model_prefix_is_bit_exact(kind: str, model: str):
    prices = _prices()
    sectors = _sectors()
    cut = 100
    base_score, base_weight = price_path(prices, sectors, model, "index_enhancement", TINY_CONFIG)
    alt_score, alt_weight = price_path(perturb(prices, cut, kind), sectors, model, "index_enhancement", TINY_CONFIG)
    assert_causal_prefix(_Path(base_score, base_weight), _Path(alt_score, alt_weight), cut)
    assert np.isfinite(base_score[cut]).all()


def test_future_labels_do_not_change_past_scores():
    prices = _prices()
    frame = build_decision_frame(prices, TINY_CONFIG)
    cut = 50
    base, _folds = CascadeDeepForest(TINY_CONFIG).predict(frame.features, frame.labels)
    boosted, _ = MultiLayerGBDT(TINY_CONFIG).predict(frame.features, frame.labels)
    labels = frame.labels.copy()
    labels[cut + 1 :] += 0.25
    alt, _ = CascadeDeepForest(TINY_CONFIG).predict(frame.features, labels)
    alt_boost, _ = MultiLayerGBDT(TINY_CONFIG).predict(frame.features, labels)
    assert_same_bits(base[: cut + 1], alt[: cut + 1])
    assert_same_bits(boosted[: cut + 1], alt_boost[: cut + 1])
    ridge, _ = CausalRidge(TINY_CONFIG).predict(frame.features, frame.labels)
    ridge_alt, _ = CausalRidge(TINY_CONFIG).predict(frame.features, labels)
    assert_same_bits(ridge[: cut + 1], ridge_alt[: cut + 1])


def test_scores_are_deterministic():
    prices = _prices()
    frame = build_decision_frame(prices, TINY_CONFIG)
    first, folds = CascadeDeepForest(TINY_CONFIG).predict(frame.features, frame.labels)
    second, _ = CascadeDeepForest(TINY_CONFIG).predict(frame.features, frame.labels)
    assert_same_bits(first, second)
    assert folds
    gbdt, _ = MultiLayerGBDT(TINY_CONFIG).predict(frame.features, frame.labels)
    again, _ = MultiLayerGBDT(TINY_CONFIG).predict(frame.features, frame.labels)
    assert_same_bits(gbdt, again)


def test_risk_box_enforces_name_sector_net_and_factor_caps():
    benchmark = np.full(4, 0.25)
    sectors = _sectors()
    box = _box()
    raw = np.array([0.90, 0.20, 0.05, -0.15])
    factors = np.array([2.5, 2.5, -0.5, -0.5])
    weights = constrain_weights(raw, benchmark, sectors, factors, None, raw, box)
    assert exposure_violations(weights, benchmark, sectors, factors, box) == []
    assert np.max(np.abs(weights - benchmark)) <= box.name_cap + 1e-8
    assert box.net_min - 1e-8 <= float(weights.sum()) <= box.net_max + 1e-8
    neutral = box_for_mode("market_neutral", 4)
    neutral_w = constrain_weights(
        np.array([0.2, 0.1, -0.1, -0.2]),
        neutral_book(4, "market_neutral"),
        sectors,
        np.ones(4),
        None,
        np.array([0.2, 0.1, -0.1, -0.2]),
        neutral,
    )
    assert abs(float(neutral_w.sum())) <= neutral.net_max + 1e-8
    assert np.max(np.abs(neutral_w)) <= neutral.abs_name_cap + 1e-8
    free = box_for_mode("unconstrained", 4)
    concentrated = constrain_weights(
        scores_to_target(np.array([5.0, 0.0, 0.0, 0.0]), benchmark, free),
        benchmark,
        sectors,
        np.ones(4),
        None,
        np.array([5.0, 0.0, 0.0, 0.0]),
        free,
    )
    assert concentrated[0] > benchmark[0] + 0.02
    assert abs(float(concentrated.sum()) - 1.0) <= 1e-8


def test_sector_cap_binds_when_the_signal_piles_into_one_sector():
    benchmark = np.full(4, 0.25)
    sectors = np.asarray(["A", "A", "B", "B"])
    box = RiskBox(
        mode="index_enhancement",
        name_cap=0.10,
        sector_cap=0.02,
        net_min=0.98,
        net_max=1.02,
        factor_cap=1.0,
        abs_name_cap=0.40,
        score_scale=0.05,
    )
    raw = benchmark + np.array([0.08, 0.08, -0.08, -0.08])
    weights = constrain_weights(raw, benchmark, sectors, np.ones(4), None, raw, box)
    active = weights - benchmark
    assert abs(float(active[:2].sum())) <= box.sector_cap + 1e-8
    assert abs(float(active[2:].sum())) <= box.sector_cap + 1e-8
    assert exposure_violations(weights, benchmark, sectors, np.ones(4), box) == []


def test_cost_step_uses_the_desk_rate():
    box = _box()
    rate = leg_rate_bps(box.commission_bps, box.half_spread_bps, box.slippage_bps) / 10_000.0
    assert box.one_way_rate == pytest.approx(rate)
    previous = np.full(4, 0.25)
    target = previous + np.array([0.02, -0.01, -0.01, 0.0])
    traded = float(np.sum(np.abs(target - previous)))
    cost = rate * traded
    paying = np.array([1.0, -1.0, -1.0, 0.0])
    assert entry_allowed(float(np.dot(paying, target - previous)), cost, k=1.0)
    assert_same_bits(_cost_step(target, previous, paying, box), target)
    flat = np.zeros(4)
    assert not entry_allowed(float(np.dot(flat, target - previous)), cost, k=1.0)
    assert_same_bits(_cost_step(target, previous, flat, box), previous)
    partial_scores = np.array([0.0001, 0.0, 0.0, 0.0])
    edge = float(np.dot(partial_scores, target - previous))
    assert 0.0 < edge < cost
    stepped = _cost_step(target, previous, partial_scores, box)
    assert_same_bits(stepped, previous + (edge / cost) * (target - previous))


def test_weight_path_is_prefix_causal():
    rng = np.random.default_rng(3)
    scores = rng.normal(0.0, 0.01, size=(40, 4))
    betas = np.ones((40, 4))
    box = box_for_mode("index_enhancement", 4)
    base = weights_from_scores(scores, betas, _sectors(), box)
    changed = scores.copy()
    changed[20:] += 0.05
    alt = weights_from_scores(changed, betas, _sectors(), box)
    assert_same_bits(base[:21], alt[:21])
    assert exposure_violations(base[-1], neutral_book(4, box.mode), _sectors(), betas[-1], box) == []


def test_book_clears_the_causal_and_cost_checks(tmp_path: Path):
    panel = _panel()
    runtime = HarnessRuntime(tmp_path)
    result = submit_study(runtime, panel, "ridge", "index_enhancement", config=TINY_CONFIG)
    assert result.eligible_for_live_trading is False
    assert result.causal_ok is True
    assert result.costs_ok is True
    assert result.paper_ok is True
    assert result.n_trials == N_TRIALS
    assert result.approved is False or result.dsr_ok is True
    assert result.terminal in {"rejected", "promoted_paper"}
    assert result.turnover_sum > 0.0
    stored = runtime.memory.lookup(result.fingerprint)
    assert stored is not None
    assert stored.status == ("promoted_paper" if result.approved else "rejected")
    assert runtime.audit.verify() >= 1
    assert runtime.budget.experiments_used == 1
    again = submit_study(runtime, panel, "ridge", "index_enhancement", config=TINY_CONFIG)
    assert again.terminal == "duplicate"
    assert runtime.budget.experiments_used == 1


def test_benchmark_grid_is_pre_registered_and_causal(tmp_path: Path):
    assert N_TRIALS == 9
    assert [model for model, _mode in REGISTERED_TRIALS].count("equal_weight") == 1
    assert "gbdt" in {model for model, _mode in REGISTERED_TRIALS}
    assert "ridge" in {model for model, _mode in REGISTERED_TRIALS}
    panel = _panel(seed=11)
    rows = run_benchmark(panel, tmp_path, config=TINY_CONFIG)
    assert len(rows) == N_TRIALS
    assert {(row.model, row.mode) for row in rows} == set(REGISTERED_TRIALS)
    for row in rows:
        assert row.eligible_for_live_trading is False
        assert row.n_trials == N_TRIALS
        assert row.causal_ok is True
        assert row.costs_ok is True
        assert row.paper_ok is True
        assert row.terminal in {"rejected", "promoted_paper"}
        assert np.isfinite(row.gross_annualized_return)
        assert np.isfinite(row.net_annualized_return)
        assert row.turnover_sum > 0.0
        assert row.fingerprint
    prepared = prepare_book(
        panel.prices, np.asarray(panel.sectors), "equal_weight", "unconstrained", config=TINY_CONFIG
    )
    assert np.allclose(prepared.weights, 1.0 / panel.prices.shape[1])


def test_tree_study_route_stays_paper(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    panel = _panel(n=120, seed=5)
    monkeypatch.setattr("app.api.harness._study_panel", lambda: panel)
    monkeypatch.setattr("app.api.harness._study_config", lambda: TINY_CONFIG)
    app = FastAPI()
    app.state.limiter = limiter
    app.state.harness = HarnessRuntime(tmp_path)
    app.include_router(router, prefix="/api/harness", dependencies=[Depends(get_current_user)])
    client = TestClient(app)
    body = {"model": "gbdt", "mode": "market_neutral", "n_trials": 2, "eligible_for_live_trading": False}
    assert client.post("/api/harness/studies/tree-ensemble", json=body).status_code == 401
    app.dependency_overrides[get_current_user] = lambda: "tester"
    created = client.post("/api/harness/studies/tree-ensemble", json=body)
    assert created.status_code == 200, created.text
    payload = created.json()
    assert payload["eligible_for_live_trading"] is False
    assert payload["n_trials"] == N_TRIALS
    assert payload["causal_ok"] is True
    assert payload["costs_ok"] is True
    assert payload["model"] == "gbdt"
    assert len(payload["pre_registered_trials"]) == N_TRIALS
    refused = dict(body)
    refused["eligible_for_live_trading"] = True
    assert client.post("/api/harness/studies/tree-ensemble", json=refused).status_code == 422
    unknown = dict(body)
    unknown["model"] = "lstm"
    assert client.post("/api/harness/studies/tree-ensemble", json=unknown).status_code == 422


def test_family_is_shared_so_the_gate_sees_the_grid():
    assert FAMILY == "b3-tree-ensemble"
