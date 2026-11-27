"""Paper study: causal tree ensembles, risk boxes, and the verifiable gate.

The search is pre-registered. Every variant is judged with N equal to that
grid (or larger), including the ones that are not the submitted row. The gate
can reject all of them. ``eligible_for_live_trading`` stays false.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

import numpy as np

from app.harness.book import assert_book_report, nav_from_gross, run_book_backtest
from app.harness.paper import ELIGIBLE_FOR_LIVE_TRADING
from app.harness.runtime import HarnessRuntime
from app.harness.types import BacktestReport, ExperimentSpec, RunOutcome
from app.models.deep_forest import (
    BENCHMARK_CONFIG,
    MODEL_NAMES,
    CascadeDeepForest,
    CausalRidge,
    DecisionFrame,
    EnsembleConfig,
    MultiLayerGBDT,
    ResearchPanel,
    align_to_prices,
    build_decision_frame,
    load_b3_research_panel,
)
from app.models.risk_box import RiskBox, box_for_mode, neutral_book, weights_from_scores
from app.models.winners_curse import annualized_sharpe

FAMILY = "b3-tree-ensemble"
PERIODS_PER_YEAR = 252.0

# Locked before any of these books is scored. Do not drop a row after seeing Sharpe.
REGISTERED_TRIALS: tuple[tuple[str, str], ...] = (
    ("cascade_forest", "unconstrained"),
    ("cascade_forest", "index_enhancement"),
    ("cascade_forest", "market_neutral"),
    ("mgbdt", "unconstrained"),
    ("mgbdt", "index_enhancement"),
    ("mgbdt", "market_neutral"),
    ("gbdt", "unconstrained"),
    ("ridge", "unconstrained"),
    ("equal_weight", "unconstrained"),
)
N_TRIALS = len(REGISTERED_TRIALS)

MODES = ("unconstrained", "index_enhancement", "market_neutral")
_COMPUTE = {"cascade_forest": 4, "mgbdt": 4, "gbdt": 2, "ridge": 1, "equal_weight": 1}


@dataclass(frozen=True, slots=True)
class PreparedBook:
    spec: ExperimentSpec
    report: BacktestReport
    scores: np.ndarray
    weights: np.ndarray
    eligible_for_live_trading: bool = False

    def __post_init__(self) -> None:
        if self.eligible_for_live_trading is not False or ELIGIBLE_FOR_LIVE_TRADING is not False:
            raise ValueError("eligible_for_live_trading must remain false")


@dataclass(frozen=True, slots=True)
class StudyResult:
    model: str
    mode: str
    gross_annualized_return: float
    net_annualized_return: float
    net_sharpe: float | None
    max_drawdown: float
    turnover_sum: float
    turnover_per_year: float
    dsr: float | None
    n_trials: int
    approved: bool
    causal_ok: bool
    costs_ok: bool
    dsr_ok: bool
    paper_ok: bool
    terminal: str
    reasons: tuple[str, ...]
    fingerprint: str
    eligible_for_live_trading: bool = False

    def __post_init__(self) -> None:
        if self.eligible_for_live_trading is not False or ELIGIBLE_FOR_LIVE_TRADING is not False:
            raise ValueError("eligible_for_live_trading must remain false")

    def to_dict(self) -> dict[str, object]:
        return {
            "model": self.model,
            "mode": self.mode,
            "gross_annualized_return": self.gross_annualized_return,
            "net_annualized_return": self.net_annualized_return,
            "net_sharpe": self.net_sharpe,
            "max_drawdown": self.max_drawdown,
            "turnover_sum": self.turnover_sum,
            "turnover_per_year": self.turnover_per_year,
            "dsr": self.dsr,
            "n_trials": self.n_trials,
            "approved": self.approved,
            "causal_ok": self.causal_ok,
            "costs_ok": self.costs_ok,
            "dsr_ok": self.dsr_ok,
            "paper_ok": self.paper_ok,
            "terminal": self.terminal,
            "reasons": list(self.reasons),
            "fingerprint": self.fingerprint,
            "pre_registered_trials": [list(item) for item in REGISTERED_TRIALS],
            "eligible_for_live_trading": ELIGIBLE_FOR_LIVE_TRADING,
        }


def prepare_book(
    prices: np.ndarray,
    sectors: np.ndarray,
    model: str,
    mode: str,
    *,
    config: EnsembleConfig = BENCHMARK_CONFIG,
    n_trials: int = N_TRIALS,
    frame: DecisionFrame | None = None,
    scores: np.ndarray | None = None,
    folds: tuple[tuple[int, int, int], ...] | None = None,
    box: RiskBox | None = None,
) -> PreparedBook:
    """Fit (or reuse) causal scores and apply the risk box. Does not call the gate."""
    _check_variant(model, mode)
    used = max(int(n_trials), N_TRIALS)
    decision = frame if frame is not None else build_decision_frame(prices, config)
    if scores is None or folds is None:
        if model == "equal_weight":
            model_scores = np.full(decision.labels.shape, np.nan, dtype=np.float64)
            model_folds = _static_fold(decision.labels.shape[0], config.embargo)
        else:
            model_scores, model_folds = _fit_scores(decision, model, config)
    else:
        model_scores, model_folds = scores, folds
    risk = (
        box
        if box is not None
        else box_for_mode(
            mode,
            decision.labels.shape[1],
            commission_bps=5.0,
            slippage_bps=5.0,
            half_spread_bps=2.0,
        )
    )
    if model == "equal_weight":
        book = np.broadcast_to(neutral_book(decision.labels.shape[1], "unconstrained"), decision.labels.shape).copy()
    else:
        book = weights_from_scores(model_scores, decision.beta, sectors, risk)
    if not np.all(np.isfinite(decision.peer_features)):
        raise ValueError("peer features must be finite on the decision grid")
    exposure = np.clip(np.sum(book, axis=1), -1.0, 1.0)
    report = run_book_backtest(
        decision.labels,
        book,
        commission_bps=risk.commission_bps,
        slippage_bps=risk.slippage_bps,
        half_spread_bps=risk.half_spread_bps,
        n_trials=used,
        embargo=config.embargo,
        folds=model_folds,
        feature_matrix=decision.peer_features,
        signal=exposure,
    )
    spec = _spec(model, mode, decision, report, exposure, used, _COMPUTE[model])
    assert_book_report(spec, report)
    return PreparedBook(spec=spec, report=report, scores=model_scores, weights=book)


def submit_study(
    runtime: HarnessRuntime,
    panel: ResearchPanel,
    model: str,
    mode: str,
    *,
    config: EnsembleConfig = BENCHMARK_CONFIG,
    n_trials: int = N_TRIALS,
    cache: dict[str, tuple[np.ndarray, tuple[tuple[int, int, int], ...]]] | None = None,
    frame: DecisionFrame | None = None,
) -> StudyResult:
    """Walk the harness: hypothesis, features, paper book, probe, gate, memory."""
    decision = frame if frame is not None else build_decision_frame(panel.prices, config)
    scores: np.ndarray | None = None
    folds: tuple[tuple[int, int, int], ...] | None = None
    if model != "equal_weight":
        if cache is not None and model in cache:
            scores, folds = cache[model]
        else:
            scores, folds = _fit_scores(decision, model, config)
            if cache is not None:
                cache[model] = (scores, folds)
    prepared = prepare_book(
        panel.prices,
        np.asarray(panel.sectors),
        model,
        mode,
        config=config,
        n_trials=n_trials,
        frame=decision,
        scores=scores,
        folds=folds,
    )
    outcome = runtime.execute(prepared.spec, report=prepared.report)
    return _result(model, mode, prepared.report, outcome)


def run_benchmark(
    panel: ResearchPanel,
    root: Path | str,
    *,
    config: EnsembleConfig = BENCHMARK_CONFIG,
) -> tuple[StudyResult, ...]:
    """All nine pre-registered books, one fresh harness directory, one shared N."""
    runtime = HarnessRuntime(root)
    frame = build_decision_frame(panel.prices, config)
    cache: dict[str, tuple[np.ndarray, tuple[tuple[int, int, int], ...]]] = {}
    results: list[StudyResult] = []
    for model, mode in REGISTERED_TRIALS:
        result = submit_study(
            runtime,
            panel,
            model,
            mode,
            config=config,
            n_trials=N_TRIALS,
            cache=cache,
            frame=frame,
        )
        if result.terminal == "duplicate":
            raise RuntimeError(f"{model}/{mode} was swallowed as a duplicate, so N would not be honest")
        results.append(result)
    return tuple(results)


def price_path(
    prices: np.ndarray,
    sectors: np.ndarray,
    model: str,
    mode: str,
    config: EnsembleConfig,
) -> tuple[np.ndarray, np.ndarray]:
    """Price-aligned scores and weights for the prefix-invariance check.

    A non-finite tail is allowed here. The harness book still refuses a
    non-finite feature matrix, because that report could not be audited.
    """
    _check_variant(model, mode)
    frame = build_decision_frame(prices, config)
    n_assets = frame.labels.shape[1]
    if model == "equal_weight":
        scores = np.full(frame.labels.shape, np.nan, dtype=np.float64)
        book = np.broadcast_to(neutral_book(n_assets, "unconstrained"), frame.labels.shape).copy()
    else:
        scores, _folds = _fit_scores(frame, model, config)
        book = weights_from_scores(scores, frame.beta, sectors, box_for_mode(mode, n_assets))
    score = align_to_prices(scores, frame.index, int(prices.shape[0]), fill=np.nan)
    weight = align_to_prices(book, frame.index, int(prices.shape[0]), fill=0.0)
    return score, weight


def _fit_scores(
    frame: DecisionFrame,
    model: str,
    config: EnsembleConfig,
) -> tuple[np.ndarray, tuple[tuple[int, int, int], ...]]:
    if model == "cascade_forest":
        return CascadeDeepForest(config).predict(frame.features, frame.labels)
    if model == "mgbdt":
        return MultiLayerGBDT(config).predict(frame.features, frame.labels)
    if model == "gbdt":
        return MultiLayerGBDT(replace(config, n_layers=1)).predict(frame.features, frame.labels)
    if model == "ridge":
        return CausalRidge(config).predict(frame.features, frame.labels)
    raise ValueError(f"unknown scored model {model!r}")


def _spec(
    model: str,
    mode: str,
    frame: DecisionFrame,
    report: BacktestReport,
    exposure: np.ndarray,
    n_trials: int,
    compute_units: int,
) -> ExperimentSpec:
    prices = nav_from_gross(np.asarray(report.gross_returns, dtype=np.float64))
    statement = f"Causal {model} next-day scores under {mode} risk boxes are a paper hypothesis on the cross-section."
    return ExperimentSpec(
        statement=statement,
        family=FAMILY,
        feature_names=frame.names,
        feature_formulas=frame.formulas,
        prices=tuple(float(v) for v in prices),
        signal=tuple(float(v) for v in exposure),
        feature_matrix=report.feature_matrix,
        lag=1,
        commission_bps=report.commission_bps,
        slippage_bps=report.slippage_bps,
        half_spread_bps=report.half_spread_bps,
        n_trials=n_trials,
        compute_units=compute_units,
    )


def _result(model: str, mode: str, report: BacktestReport, outcome: RunOutcome) -> StudyResult:
    gross = np.asarray(report.gross_returns, dtype=np.float64)
    net = np.asarray(report.net_returns, dtype=np.float64)
    turnover = np.asarray(report.turnover, dtype=np.float64)
    checks = dict(outcome.checks)
    sharpe = outcome.observed_sharpe
    if sharpe is None and len(net) >= 3:
        sharpe = annualized_sharpe(net, PERIODS_PER_YEAR)
    return StudyResult(
        model=model,
        mode=mode,
        gross_annualized_return=_compound_annual(gross),
        net_annualized_return=_compound_annual(net),
        net_sharpe=sharpe,
        max_drawdown=_max_drawdown(net),
        turnover_sum=float(np.sum(turnover)),
        turnover_per_year=float(np.sum(turnover) / (len(turnover) / PERIODS_PER_YEAR)),
        dsr=outcome.dsr,
        n_trials=N_TRIALS if outcome.n_trials_used is None else int(outcome.n_trials_used),
        approved=bool(outcome.approved),
        causal_ok=bool(checks.get("causal", False)),
        costs_ok=bool(checks.get("costs", False)),
        dsr_ok=bool(checks.get("dsr", False)),
        paper_ok=bool(checks.get("paper", False)),
        terminal=outcome.terminal,
        reasons=outcome.reasons,
        fingerprint=outcome.fingerprint,
    )


def _compound_annual(returns: np.ndarray) -> float:
    wealth = float(np.prod(1.0 + returns))
    years = len(returns) / PERIODS_PER_YEAR
    if years <= 0.0 or not np.isfinite(wealth) or wealth <= 0.0:
        return float("nan")
    return float(wealth ** (1.0 / years) - 1.0)


def _max_drawdown(returns: np.ndarray) -> float:
    equity = np.cumprod(1.0 + returns)
    peak = np.maximum.accumulate(equity)
    return float(np.max(1.0 - equity / peak))


def _static_fold(n: int, embargo: int) -> tuple[tuple[int, int, int], ...]:
    train_end = n // 2
    test_start = train_end + embargo + 1
    if test_start >= n or train_end < 0:
        raise ValueError("sample is too short for the embargoed split")
    return ((train_end, test_start, embargo),)


def _check_variant(model: str, mode: str) -> None:
    if model not in MODEL_NAMES:
        raise ValueError(f"unknown model {model!r}")
    if mode not in MODES:
        raise ValueError(f"unknown risk-box mode {mode!r}")


def load_benchmark_panel() -> ResearchPanel:
    return load_b3_research_panel()


def main() -> None:
    """Run the pre-registered B3 benchmark and print the gate's numbers."""
    import tempfile

    panel = load_benchmark_panel()
    with tempfile.TemporaryDirectory(prefix="atom-tree-") as directory:
        rows = run_benchmark(panel, directory)
    print(f"family={FAMILY} N={N_TRIALS} sessions={panel.prices.shape[0]} names={panel.prices.shape[1]}")
    print(
        f"{'model':<16} {'mode':<20} {'gross_ann':>10} {'net_ann':>10} "
        f"{'sharpe':>8} {'dsr':>8} {'max_dd':>8} {'turnover':>10} verdict"
    )
    for row in rows:
        sharpe = "nan" if row.net_sharpe is None else f"{row.net_sharpe:.4f}"
        dsr = "nan" if row.dsr is None else f"{row.dsr:.4f}"
        verdict = "pass" if row.approved else "fail"
        print(
            f"{row.model:<16} {row.mode:<20} {row.gross_annualized_return:10.4%} "
            f"{row.net_annualized_return:10.4%} {sharpe:>8} {dsr:>8} "
            f"{row.max_drawdown:8.4%} {row.turnover_sum:10.4f} {verdict}"
        )
        if row.reasons:
            print("  " + " | ".join(row.reasons))


if __name__ == "__main__":
    main()
