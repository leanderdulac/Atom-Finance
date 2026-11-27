"""Causal cascade forest and multi-layer gradient boosting.

Both families are walk-forward. A model that scores decision ``t`` is fit only
on decisions ``i < t - embargo - 1``, so the label of the last training row
ends before the test, with the harness embargo gap. Cascade layers append
those out-of-fold scores to the original features. They never append an
in-sample fitted value. Gradient-boosting depth is chosen on a trailing slice
of that same past, then frozen.

Forests use ``random_state`` and ``n_jobs=1``. Paper only:
``eligible_for_live_trading`` stays false. This module does not size or send
an order.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import cast

import numpy as np
from sklearn.ensemble import ExtraTreesRegressor, GradientBoostingRegressor, RandomForestRegressor
from sklearn.linear_model import Ridge

from app.models._causal import ELIGIBLE_FOR_LIVE_TRADING

MODEL_NAMES = ("cascade_forest", "mgbdt", "gbdt", "ridge", "equal_weight")

# B3 names in the committed pairs-research tape, with the sector used by the box.
B3_SECTORS: dict[str, str] = {
    "PETR3": "Energia",
    "PETR4": "Energia",
    "VALE3": "Mineracao",
    "CSNA3": "Siderurgia",
    "GGBR4": "Siderurgia",
    "USIM5": "Siderurgia",
    "ITUB4": "Financeiro",
    "BBDC4": "Financeiro",
    "CMIG3": "Utilidade",
    "CMIG4": "Utilidade",
}

FitBlock = Callable[[np.ndarray, np.ndarray, np.ndarray, np.ndarray], tuple[np.ndarray, np.ndarray]]


@dataclass(frozen=True, slots=True)
class EnsembleConfig:
    """Locked hyperparameters. The walk-forward does not retune them on the test."""

    n_layers: int = 2
    n_estimators: int = 16
    max_depth: int = 3
    min_samples_leaf: int = 20
    max_boost_rounds: int = 30
    learning_rate: float = 0.05
    patience: int = 4
    min_train: int = 252
    embargo: int = 1
    refit_every: int = 63
    val_size: int = 42
    mom_fast: int = 5
    mom_slow: int = 21
    vol_window: int = 21
    beta_window: int = 63
    ridge_alpha: float = 10.0
    seed: int = 0
    eligible_for_live_trading: bool = False

    def __post_init__(self) -> None:
        if self.eligible_for_live_trading is not False or ELIGIBLE_FOR_LIVE_TRADING is not False:
            raise ValueError("eligible_for_live_trading must remain false")
        _positive("n_layers", self.n_layers, 1)
        _positive("n_estimators", self.n_estimators, 1)
        _positive("max_depth", self.max_depth, 1)
        _positive("min_samples_leaf", self.min_samples_leaf, 1)
        _positive("max_boost_rounds", self.max_boost_rounds, 1)
        _positive("patience", self.patience, 1)
        _positive("min_train", self.min_train, 8)
        _positive("embargo", self.embargo, 1)
        _positive("refit_every", self.refit_every, 1)
        _positive("val_size", self.val_size, 2)
        _positive("mom_fast", self.mom_fast, 2)
        _positive("mom_slow", self.mom_slow, 2)
        _positive("vol_window", self.vol_window, 2)
        _positive("beta_window", self.beta_window, 2)
        _positive("seed", self.seed, 0)
        if not np.isfinite(self.learning_rate) or self.learning_rate <= 0.0:
            raise ValueError("learning_rate must be finite and > 0")
        if not np.isfinite(self.ridge_alpha) or self.ridge_alpha <= 0.0:
            raise ValueError("ridge_alpha must be finite and > 0")
        if self.mom_fast > self.mom_slow:
            raise ValueError("mom_fast cannot exceed mom_slow")

    @property
    def lookback(self) -> int:
        return max(self.mom_slow, self.vol_window, self.beta_window)


def _positive(name: str, value: int, minimum: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{name} must be an integer >= {minimum}")


BENCHMARK_CONFIG = EnsembleConfig()

TINY_CONFIG = EnsembleConfig(
    n_layers=2,
    n_estimators=4,
    max_depth=2,
    min_samples_leaf=2,
    max_boost_rounds=6,
    learning_rate=0.1,
    patience=2,
    min_train=16,
    embargo=1,
    refit_every=8,
    val_size=4,
    mom_fast=3,
    mom_slow=5,
    vol_window=5,
    beta_window=8,
    ridge_alpha=10.0,
    seed=0,
)


@dataclass(frozen=True, slots=True)
class ResearchPanel:
    names: tuple[str, ...]
    sectors: tuple[str, ...]
    dates: tuple[str, ...]
    prices: np.ndarray
    eligible_for_live_trading: bool = False

    def __post_init__(self) -> None:
        if self.eligible_for_live_trading is not False or ELIGIBLE_FOR_LIVE_TRADING is not False:
            raise ValueError("eligible_for_live_trading must remain false")
        prices = np.asarray(self.prices, dtype=np.float64)
        if prices.ndim != 2 or prices.shape[0] < 30 or prices.shape[1] < 2:
            raise ValueError("prices must have shape (time, asset) with time >= 30 and assets >= 2")
        if prices.shape[1] != len(self.names) or len(self.sectors) != len(self.names):
            raise ValueError("names, sectors, and price columns must align")
        if len(self.dates) != prices.shape[0]:
            raise ValueError("dates must align with price rows")
        if not np.all(np.isfinite(prices)) or np.any(prices <= 0.0):
            raise ValueError("panel prices must be finite and strictly positive")
        object.__setattr__(self, "prices", prices)


@dataclass(frozen=True, slots=True)
class DecisionFrame:
    """One row per decision. ``labels[t]`` is the next return, unknown at ``t``."""

    index: np.ndarray
    features: np.ndarray
    labels: np.ndarray
    beta: np.ndarray
    peer_features: np.ndarray
    names: tuple[str, ...]
    formulas: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PricePath:
    """Price-aligned scores and weights. Non-decision rows are NaN scores and zero weights."""

    score: np.ndarray
    weight: np.ndarray
    eligible_for_live_trading: bool = False

    def __post_init__(self) -> None:
        if self.eligible_for_live_trading is not False or ELIGIBLE_FOR_LIVE_TRADING is not False:
            raise ValueError("eligible_for_live_trading must remain false")


def feature_spec(config: EnsembleConfig) -> tuple[tuple[str, ...], tuple[str, ...]]:
    names = ("ret_1", "mom_fast", "mom_slow", "vol", "cs_mom", "beta")
    formulas = (
        "close-to-close return known at the decision bar",
        f"{config.mom_fast}-session price change known at the decision bar",
        f"{config.mom_slow}-session price change known at the decision bar",
        f"{config.vol_window}-session return volatility known at the decision bar",
        "cross-sectional momentum minus the same-bar peer mean",
        f"{config.beta_window}-session beta to the equal-weight peer mean, known at the decision bar",
    )
    return names, formulas


def load_b3_research_panel(fixture_dir: Path | str | None = None) -> ResearchPanel:
    """Aligned adjusted closes from the committed B3 pairs tape. No network."""
    root = Path(fixture_dir) if fixture_dir is not None else _default_fixture_dir()
    series = {name: _read_closes(root / f"{name}.json") for name in B3_SECTORS}
    common = set.intersection(*(set(values) for values in series.values()))
    anchor = series["PETR4"]
    dates = tuple(day for day in anchor if day in common)
    if len(dates) < 30:
        raise ValueError("B3 research panel is shorter than 30 sessions")
    columns = [[series[name][day] for day in dates] for name in B3_SECTORS]
    prices = np.column_stack([np.asarray(col, dtype=np.float64) for col in columns])
    names = tuple(B3_SECTORS)
    sectors = tuple(B3_SECTORS[name] for name in names)
    return ResearchPanel(names=names, sectors=sectors, dates=dates, prices=prices)


def build_decision_frame(prices: np.ndarray, config: EnsembleConfig) -> DecisionFrame:
    """Features at close t use prices through t. The label is the return to t+1."""
    px = np.asarray(prices, dtype=np.float64)
    if px.ndim != 2 or px.shape[1] < 2:
        raise ValueError("prices must have shape (time, asset)")
    lookback = config.lookback
    if px.shape[0] <= lookback + config.min_train + config.embargo + 2:
        raise ValueError("price history is too short for the embargoed walk-forward")
    returns = _simple_returns(px)
    mom_fast = _price_change(px, config.mom_fast)
    mom_slow = _price_change(px, config.mom_slow)
    vol = _rolling_vol(returns, config.vol_window)
    beta = _rolling_beta(returns, config.beta_window)
    cs_mom = mom_slow - _mean_over_assets(mom_slow)[:, None]
    stacked = np.stack([returns, mom_fast, mom_slow, vol, cs_mom, beta], axis=-1)
    index = np.arange(lookback, px.shape[0] - 1, dtype=np.int64)
    features = stacked[index]
    labels = returns[index + 1]
    peer = _mean_over_assets(features)
    names, formulas = feature_spec(config)
    return DecisionFrame(
        index=index,
        features=features,
        labels=labels,
        beta=beta[index],
        peer_features=peer,
        names=names,
        formulas=formulas,
    )


def train_end_exclusive(test_start: int, embargo: int) -> int:
    """Exclusive end of the training decisions for a test that starts at ``test_start``.

    The harness accepts a fold only when ``test_start >= train_end + embargo + 1``.
    """
    if embargo < 1 or test_start < embargo + 1:
        raise ValueError("embargo and test_start cannot describe a causal fold")
    return test_start - embargo - 1


def walk_forward_predict(
    features: np.ndarray,
    labels: np.ndarray,
    *,
    config: EnsembleConfig,
    represent_dim: int,
    fit_block: FitBlock,
) -> tuple[np.ndarray, np.ndarray, tuple[tuple[int, int, int], ...]]:
    """Out-of-fold scores. Training rows are strictly before ``test_start - embargo - 1``."""
    x = np.asarray(features, dtype=np.float64)
    y = np.asarray(labels, dtype=np.float64)
    if x.ndim != 3 or y.ndim != 2 or x.shape[:2] != y.shape:
        raise ValueError("features must be (time, asset, feature) and labels (time, asset)")
    if represent_dim < 1:
        raise ValueError("represent_dim must be >= 1")
    n_time, n_asset, _ = x.shape
    pred = np.full((n_time, n_asset), np.nan, dtype=np.float64)
    represented = np.full((n_time, n_asset, represent_dim), np.nan, dtype=np.float64)
    first = config.min_train + config.embargo + 1
    if first >= n_time:
        raise ValueError("sample is too short for the embargoed walk-forward")
    folds: list[tuple[int, int, int]] = []
    t = first
    while t < n_time:
        train_end = train_end_exclusive(t, config.embargo)
        nxt = min(n_time, t + config.refit_every)
        x_train, y_train, t_train, _ = _gather(x, y, 0, train_end, require_label=True)
        x_block, _, t_block, a_block = _gather(x, y, t, nxt, require_label=False)
        enough_history = len(t_train) > 0 and len(np.unique(t_train)) >= config.min_train
        if enough_history and len(y_train) >= config.min_samples_leaf and len(t_block) > 0:
            block_pred, block_rep = fit_block(t_train, x_train, y_train, x_block)
            block_pred = np.asarray(block_pred, dtype=np.float64)
            block_rep = np.asarray(block_rep, dtype=np.float64)
            if block_pred.shape != (len(t_block),) or block_rep.shape != (len(t_block), represent_dim):
                raise ValueError("fit_block returned a mis-shaped prediction")
            bad = ~np.isfinite(block_pred)
            block_pred = block_pred.copy()
            block_rep = block_rep.copy()
            block_pred[bad] = np.nan
            block_rep[~np.all(np.isfinite(block_rep), axis=1)] = np.nan
            pred[t_block, a_block] = block_pred
            represented[t_block, a_block] = block_rep
            folds.append((train_end, t, config.embargo))
        t = nxt
    return pred, represented, tuple(folds)


class CascadeDeepForest:
    """gcForest-style cascade: RandomForest and ExtraTrees, causal layer by layer."""

    eligible_for_live_trading = False

    def __init__(self, config: EnsembleConfig | None = None) -> None:
        self.config = BENCHMARK_CONFIG if config is None else config

    def predict(self, features: np.ndarray, labels: np.ndarray) -> tuple[np.ndarray, tuple[tuple[int, int, int], ...]]:
        current = np.asarray(features, dtype=np.float64)
        raw = current
        pred = np.full(labels.shape[:2], np.nan, dtype=np.float64)
        folds: tuple[tuple[int, int, int], ...] = ()
        for layer in range(self.config.n_layers):
            seed = self.config.seed + 17 * layer
            pred, represented, folds = walk_forward_predict(
                current,
                labels,
                config=self.config,
                represent_dim=2,
                fit_block=_forest_block(self.config, seed),
            )
            if layer + 1 < self.config.n_layers:
                current = np.concatenate([raw, represented], axis=-1)
        if not folds:
            raise ValueError("cascade forest produced no causal fold")
        return pred, folds


class MultiLayerGBDT:
    """mGBDT-style stack. ``n_layers=1`` is the single-layer GBDT baseline.

    Each layer's round count is chosen on a trailing past slice, then the
    layer is refit on the whole eligible past with that count frozen.
    """

    eligible_for_live_trading = False

    def __init__(self, config: EnsembleConfig | None = None) -> None:
        self.config = BENCHMARK_CONFIG if config is None else config

    def predict(self, features: np.ndarray, labels: np.ndarray) -> tuple[np.ndarray, tuple[tuple[int, int, int], ...]]:
        current = np.asarray(features, dtype=np.float64)
        raw = current
        pred = np.full(labels.shape[:2], np.nan, dtype=np.float64)
        folds: tuple[tuple[int, int, int], ...] = ()
        for layer in range(self.config.n_layers):
            seed = self.config.seed + 29 * layer
            pred, represented, folds = walk_forward_predict(
                current,
                labels,
                config=self.config,
                represent_dim=2,
                fit_block=_gbdt_block(self.config, seed),
            )
            if layer + 1 < self.config.n_layers:
                current = np.concatenate([raw, represented], axis=-1)
        if not folds:
            raise ValueError("layered GBDT produced no causal fold")
        return pred, folds


class CausalRidge:
    """Single-layer ridge baseline on the same embargoed walk-forward."""

    eligible_for_live_trading = False

    def __init__(self, config: EnsembleConfig | None = None) -> None:
        self.config = BENCHMARK_CONFIG if config is None else config

    def predict(self, features: np.ndarray, labels: np.ndarray) -> tuple[np.ndarray, tuple[tuple[int, int, int], ...]]:
        pred, _, folds = walk_forward_predict(
            features,
            labels,
            config=self.config,
            represent_dim=1,
            fit_block=_ridge_block(self.config),
        )
        if not folds:
            raise ValueError("ridge produced no causal fold")
        return pred, folds


def predict_scores(
    prices: np.ndarray,
    model: str,
    config: EnsembleConfig,
) -> tuple[DecisionFrame, np.ndarray, tuple[tuple[int, int, int], ...]]:
    """Decision-grid scores for one model. Equal weight has no score."""
    if model not in MODEL_NAMES or model == "equal_weight":
        raise ValueError(f"unknown scored model {model!r}")
    frame = build_decision_frame(prices, config)
    if model == "cascade_forest":
        scores, folds = CascadeDeepForest(config).predict(frame.features, frame.labels)
    elif model == "mgbdt":
        scores, folds = MultiLayerGBDT(config).predict(frame.features, frame.labels)
    elif model == "gbdt":
        scores, folds = MultiLayerGBDT(replace(config, n_layers=1)).predict(frame.features, frame.labels)
    else:
        scores, folds = CausalRidge(config).predict(frame.features, frame.labels)
    return frame, scores, folds


def align_to_prices(values: np.ndarray, index: np.ndarray, n_prices: int, *, fill: float) -> np.ndarray:
    out = np.full((n_prices, values.shape[1]), fill, dtype=np.float64)
    out[index] = values
    return out


def _default_fixture_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "pairs_real"


def _read_closes(path: Path) -> dict[str, float]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    out: dict[str, float] = {}
    for day, px in zip(payload["dates"], payload["close"], strict=True):
        if px is None:
            continue
        value = float(px)
        if np.isfinite(value) and value > 0.0:
            out[str(day)] = value
    if len(out) < 30:
        raise ValueError(f"{path.name} has fewer than 30 positive closes")
    return out


def _simple_returns(prices: np.ndarray) -> np.ndarray:
    prev = prices[:-1]
    nxt = prices[1:]
    good = np.isfinite(prev) & np.isfinite(nxt) & (prev > 0.0) & (nxt > 0.0)
    vals = np.full(prev.shape, np.nan, dtype=np.float64)
    vals[good] = nxt[good] / prev[good] - 1.0
    out = np.full(prices.shape, np.nan, dtype=np.float64)
    out[1:] = vals
    return out


def _price_change(prices: np.ndarray, window: int) -> np.ndarray:
    prev = prices[:-window]
    nxt = prices[window:]
    good = np.isfinite(prev) & np.isfinite(nxt) & (prev > 0.0) & (nxt > 0.0)
    vals = np.full(prev.shape, np.nan, dtype=np.float64)
    vals[good] = nxt[good] / prev[good] - 1.0
    out = np.full(prices.shape, np.nan, dtype=np.float64)
    out[window:] = vals
    return out


def _rolling_sum(values: np.ndarray, window: int) -> np.ndarray:
    """Sum of ``window`` rows ending at t, NaN until the window is full.

    ``cumsum`` is causal: a non-finite value at ``t`` does not change sums that
    end before ``t``.
    """
    series = np.asarray(values, dtype=np.float64)
    cumulative = np.cumsum(series, axis=0)
    out = np.full(series.shape, np.nan, dtype=np.float64)
    if series.shape[0] < window:
        return out
    total = cumulative[window - 1 :]
    prev = np.zeros_like(total)
    prev[1:] = cumulative[: total.shape[0] - 1]
    out[window - 1 :] = total - prev
    return out


def _rolling_sum_masked(values: np.ndarray, window: int) -> np.ndarray:
    """Rolling sum that stays finite only when every bar in the window is finite.

    Non-finite bars are zeros in the cumsum and fail the count, so a hole does
    not poison earlier windows.
    """
    finite = np.isfinite(values)
    clean = np.where(finite, values, 0.0)
    total = _rolling_sum(clean, window)
    count = _rolling_sum(finite.astype(np.float64), window)
    total = np.array(total, copy=True)
    total[~(count >= window)] = np.nan
    return total


def _rolling_vol(returns: np.ndarray, window: int) -> np.ndarray:
    sum_r = _rolling_sum_masked(returns, window)
    sum_r2 = _rolling_sum_masked(returns * returns, window)
    mean = sum_r / window
    var = np.maximum(sum_r2 / window - mean * mean, 0.0)
    with np.errstate(invalid="ignore"):
        vol = np.sqrt(var)
    vol[~np.isfinite(sum_r)] = np.nan
    return vol


def _mean_over_assets(values: np.ndarray) -> np.ndarray:
    """Mean across assets (axis 1), ignoring non-finite entries."""
    finite = np.isfinite(values)
    count = finite.sum(axis=1)
    total = np.where(finite, values, 0.0).sum(axis=1)
    out = np.full(count.shape, np.nan, dtype=np.float64)
    ok = count > 0
    out[ok] = total[ok] / count[ok]
    return out


def _rolling_beta(returns: np.ndarray, window: int) -> np.ndarray:
    market = _mean_over_assets(returns)
    sum_x = _rolling_sum_masked(market, window)
    sum_x2 = _rolling_sum_masked(market * market, window)
    sum_y = _rolling_sum_masked(returns, window)
    sum_xy = _rolling_sum_masked(returns * market[:, None], window)
    mean_x = sum_x / window
    mean_y = sum_y / window
    var_x = np.maximum(sum_x2 / window - mean_x * mean_x, 0.0)
    cov = sum_xy / window - mean_x[:, None] * mean_y
    beta = np.ones(returns.shape, dtype=np.float64)
    beta[~np.isfinite(sum_y)] = np.nan
    ok = (var_x > 1e-18)[:, None] & np.isfinite(cov)
    beta[ok] = cov[ok] / np.broadcast_to(var_x[:, None], cov.shape)[ok]
    return beta


def _gather(
    features: np.ndarray,
    labels: np.ndarray,
    start: int,
    end: int,
    *,
    require_label: bool,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    block_x = features[start:end]
    block_y = labels[start:end]
    n_time, n_asset, n_feat = block_x.shape
    if n_time == 0:
        empty_x = np.zeros((0, n_feat), dtype=np.float64)
        empty = np.zeros(0, dtype=np.float64)
        empty_i = np.zeros(0, dtype=np.int64)
        return empty_x, empty, empty_i, empty_i
    times = np.repeat(np.arange(start, end, dtype=np.int64), n_asset)
    assets = np.tile(np.arange(n_asset, dtype=np.int64), n_time)
    flat_x = np.ascontiguousarray(block_x.reshape(-1, n_feat))
    flat_y = np.ascontiguousarray(block_y.reshape(-1))
    finite = np.all(np.isfinite(flat_x), axis=1)
    if require_label:
        finite = finite & np.isfinite(flat_y)
    return flat_x[finite], flat_y[finite], times[finite], assets[finite]


def _forest_block(config: EnsembleConfig, seed: int) -> FitBlock:
    def fit_block(
        train_times: np.ndarray,
        x_train: np.ndarray,
        y_train: np.ndarray,
        x_block: np.ndarray,
    ) -> tuple[np.ndarray, np.ndarray]:
        del train_times
        # The installed stub types max_features as float. sklearn still accepts "sqrt".
        sqrt_features = cast(float, "sqrt")
        rf = RandomForestRegressor(
            n_estimators=config.n_estimators,
            max_depth=config.max_depth,
            min_samples_leaf=config.min_samples_leaf,
            max_features=sqrt_features,
            bootstrap=True,
            random_state=seed,
            n_jobs=1,
        )
        extra = ExtraTreesRegressor(
            n_estimators=config.n_estimators,
            max_depth=config.max_depth,
            min_samples_leaf=config.min_samples_leaf,
            max_features=sqrt_features,
            bootstrap=False,
            random_state=seed + 1,
            n_jobs=1,
        )
        rf.fit(x_train, y_train)
        extra.fit(x_train, y_train)
        rf_hat = np.asarray(rf.predict(x_block), dtype=np.float64)
        extra_hat = np.asarray(extra.predict(x_block), dtype=np.float64)
        return 0.5 * (rf_hat + extra_hat), np.column_stack([rf_hat, extra_hat])

    return fit_block


def _gbdt_block(config: EnsembleConfig, seed: int) -> FitBlock:
    def fit_block(
        train_times: np.ndarray,
        x_train: np.ndarray,
        y_train: np.ndarray,
        x_block: np.ndarray,
    ) -> tuple[np.ndarray, np.ndarray]:
        rounds = _select_rounds(train_times, x_train, y_train, config, seed)
        model = _gbdt(config, seed, rounds)
        model.fit(x_train, y_train)
        full = np.asarray(model.predict(x_block), dtype=np.float64)
        mid_n = max(rounds // 2, 1)
        mid = full
        for step, staged in enumerate(model.staged_predict(x_block), start=1):
            if step == mid_n:
                mid = np.asarray(staged, dtype=np.float64)
                break
        return full, np.column_stack([full, mid])

    return fit_block


def _select_rounds(
    train_times: np.ndarray,
    x_train: np.ndarray,
    y_train: np.ndarray,
    config: EnsembleConfig,
    seed: int,
) -> int:
    """Pick the boosting round on a trailing past slice. The test block is not an argument."""
    fallback = min(config.max_boost_rounds, max(2, len(y_train) // 5))
    order = np.unique(train_times)
    if len(order) < config.val_size + config.embargo + 4:
        return fallback
    val_times = order[-config.val_size :]
    val_start = int(val_times[0])
    train_cut = val_start - config.embargo - 1
    train_mask = train_times < train_cut
    val_mask = np.isin(train_times, val_times)
    if int(train_mask.sum()) < 4 or int(val_mask.sum()) < 2:
        return fallback
    probe = _gbdt(config, seed, config.max_boost_rounds)
    probe.fit(x_train[train_mask], y_train[train_mask])
    best_n = 1
    best_loss = float("inf")
    stall = 0
    y_val = y_train[val_mask]
    x_val = x_train[val_mask]
    for step, staged in enumerate(probe.staged_predict(x_val), start=1):
        loss = float(np.mean((np.asarray(staged, dtype=np.float64) - y_val) ** 2))
        if loss < best_loss - 1e-15:
            best_loss = loss
            best_n = step
            stall = 0
        else:
            stall += 1
            if stall >= config.patience:
                break
    return best_n


def _gbdt(config: EnsembleConfig, seed: int, rounds: int) -> GradientBoostingRegressor:
    return GradientBoostingRegressor(
        n_estimators=int(rounds),
        learning_rate=config.learning_rate,
        max_depth=config.max_depth,
        min_samples_leaf=config.min_samples_leaf,
        subsample=1.0,
        random_state=seed,
    )


def _ridge_block(config: EnsembleConfig) -> FitBlock:
    def fit_block(
        train_times: np.ndarray,
        x_train: np.ndarray,
        y_train: np.ndarray,
        x_block: np.ndarray,
    ) -> tuple[np.ndarray, np.ndarray]:
        del train_times
        mu = x_train.mean(axis=0)
        sd = x_train.std(axis=0)
        sd = np.where(sd < 1e-12, 1.0, sd)
        model = Ridge(alpha=config.ridge_alpha)
        model.fit((x_train - mu) / sd, y_train)
        hat = np.asarray(model.predict((x_block - mu) / sd), dtype=np.float64)
        return hat, hat[:, None]

    return fit_block
