"""Paper risk boxes for a cross-sectional book.

A box clips a target to single-name, sector, net, and factor bounds, then
shrinks the trade when the predicted edge does not pay the desk's one-way
cost (fee + half-spread + slippage). The feasible set is convex, so a blend
of two feasible books stays inside the box.

Nothing here sends an order. ``eligible_for_live_trading`` stays false.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from app.models._causal import ELIGIBLE_FOR_LIVE_TRADING
from app.models.trading_costs import entry_allowed, leg_rate_bps

_MODES = frozenset({"index_enhancement", "market_neutral", "unconstrained"})


@dataclass(frozen=True, slots=True)
class RiskBox:
    """Explicit exposure limits. Caps are fractions of net asset value."""

    mode: str
    name_cap: float
    sector_cap: float
    net_min: float
    net_max: float
    factor_cap: float
    abs_name_cap: float
    score_scale: float = 0.01
    commission_bps: float = 5.0
    slippage_bps: float = 5.0
    half_spread_bps: float = 2.0
    eligible_for_live_trading: bool = False

    def __post_init__(self) -> None:
        if self.eligible_for_live_trading is not False or ELIGIBLE_FOR_LIVE_TRADING is not False:
            raise ValueError("eligible_for_live_trading must remain false")
        if self.mode not in _MODES:
            raise ValueError(f"unknown risk-box mode {self.mode!r}")
        for name in ("name_cap", "sector_cap", "factor_cap", "abs_name_cap", "score_scale"):
            value = float(getattr(self, name))
            if not np.isfinite(value) or value < 0.0:
                raise ValueError(f"{name} must be finite and >= 0")
        if self.score_scale <= 0.0 and self.mode != "unconstrained":
            raise ValueError("score_scale must be positive")
        if not np.isfinite(self.net_min) or not np.isfinite(self.net_max) or self.net_min > self.net_max:
            raise ValueError("net bounds must be finite with net_min <= net_max")
        for name in ("commission_bps", "slippage_bps", "half_spread_bps"):
            value = float(getattr(self, name))
            if not np.isfinite(value) or value < 0.0:
                raise ValueError(f"{name} must be finite and >= 0")

    @property
    def one_way_rate(self) -> float:
        """Fraction of traded notional charged by fee, half-spread, and slippage."""
        return leg_rate_bps(self.commission_bps, self.half_spread_bps, self.slippage_bps) / 10_000.0


def box_for_mode(
    mode: str,
    n_assets: int,
    *,
    commission_bps: float = 5.0,
    slippage_bps: float = 5.0,
    half_spread_bps: float = 2.0,
) -> RiskBox:
    """Tight index-enhancement and market-neutral boxes, plus an unbound long-only book."""
    if isinstance(n_assets, bool) or not isinstance(n_assets, int) or n_assets < 2:
        raise ValueError("n_assets must be an integer >= 2")
    if mode == "index_enhancement":
        name_cap = 0.02
        return RiskBox(
            mode=mode,
            name_cap=name_cap,
            sector_cap=0.02,
            net_min=0.98,
            net_max=1.02,
            factor_cap=0.05,
            abs_name_cap=min(1.0, 1.0 / n_assets + name_cap),
            score_scale=0.01,
            commission_bps=commission_bps,
            slippage_bps=slippage_bps,
            half_spread_bps=half_spread_bps,
        )
    if mode == "market_neutral":
        return RiskBox(
            mode=mode,
            name_cap=0.02,
            sector_cap=0.02,
            net_min=-0.02,
            net_max=0.02,
            factor_cap=0.05,
            abs_name_cap=0.02,
            score_scale=0.01,
            commission_bps=commission_bps,
            slippage_bps=slippage_bps,
            half_spread_bps=half_spread_bps,
        )
    if mode == "unconstrained":
        return RiskBox(
            mode=mode,
            name_cap=1.0,
            sector_cap=2.0,
            net_min=1.0,
            net_max=1.0,
            factor_cap=1.0e3,
            abs_name_cap=1.0,
            score_scale=1.0,
            commission_bps=commission_bps,
            slippage_bps=slippage_bps,
            half_spread_bps=half_spread_bps,
        )
    raise ValueError(f"unknown risk-box mode {mode!r}")


def neutral_book(n_assets: int, mode: str) -> np.ndarray:
    """Benchmark the box is measured against. Market-neutral uses zeros."""
    if mode == "market_neutral":
        return np.zeros(n_assets, dtype=np.float64)
    return np.full(n_assets, 1.0 / n_assets, dtype=np.float64)


def scores_to_target(scores: np.ndarray, benchmark: np.ndarray, box: RiskBox) -> np.ndarray:
    """Map a cross-section of scores into a pre-projection target."""
    s = np.asarray(scores, dtype=np.float64)
    b = np.asarray(benchmark, dtype=np.float64)
    if s.shape != b.shape or s.ndim != 1:
        raise ValueError("scores and benchmark must be 1-D and aligned")
    if box.mode == "unconstrained":
        z = _zscore(s)
        shifted = z - float(np.min(z))
        total = float(shifted.sum())
        if total <= 1e-15:
            return b.copy()
        return shifted / total
    z = _zscore(s)
    if box.mode == "market_neutral":
        return z * box.score_scale
    return b + z * box.score_scale


def constrain_weights(
    raw: np.ndarray,
    benchmark: np.ndarray,
    sectors: np.ndarray,
    factors: np.ndarray,
    previous: np.ndarray | None,
    scores: np.ndarray,
    box: RiskBox,
) -> np.ndarray:
    """Project ``raw`` onto the box, then shrink the step by the one-way cost."""
    target_raw = np.asarray(raw, dtype=np.float64)
    bench = np.asarray(benchmark, dtype=np.float64)
    factor = np.asarray(factors, dtype=np.float64)
    if factor.ndim == 1:
        factor = factor[:, None]
    if target_raw.shape != bench.shape or target_raw.ndim != 1:
        raise ValueError("raw weights and benchmark must be 1-D and aligned")
    if factor.shape[0] != bench.shape[0]:
        raise ValueError("factor rows must match the cross-section")
    if len(sectors) != bench.shape[0]:
        raise ValueError("sectors must match the cross-section")
    lo, hi = _bounds(bench, box)
    groups = _sector_groups(sectors)
    if not _feasible(bench, bench, groups, factor, box, lo, hi):
        raise ValueError("benchmark is outside the risk box")
    target = _feasible_point(target_raw, bench, groups, factor, box, lo, hi)
    if previous is None:
        return target
    prev = np.asarray(previous, dtype=np.float64)
    if prev.shape != bench.shape or not _feasible(prev, bench, groups, factor, box, lo, hi):
        return target
    return _cost_step(target, prev, scores, box)


def weights_from_scores(
    scores: np.ndarray,
    betas: np.ndarray,
    sectors: np.ndarray,
    box: RiskBox,
) -> np.ndarray:
    """Causal book: day t uses scores and betas at t and the weight at t-1.

    Rows that are not yet finite hold the neutral book (zeros when the mode is
    market-neutral). Later rows cannot change earlier weights.
    """
    s = np.asarray(scores, dtype=np.float64)
    b = np.asarray(betas, dtype=np.float64)
    if s.ndim != 2 or s.shape != b.shape:
        raise ValueError("scores and betas must share shape (time, asset)")
    n_time, n_assets = s.shape
    benchmark = neutral_book(n_assets, box.mode)
    out = np.zeros((n_time, n_assets), dtype=np.float64)
    previous: np.ndarray | None = None
    for t in range(n_time):
        finite = bool(np.all(np.isfinite(s[t])))
        if finite:
            raw = scores_to_target(s[t], benchmark, box)
            factor_t = np.where(np.isfinite(b[t]), b[t], 1.0)
            edge = s[t]
        else:
            raw = benchmark.copy()
            factor_t = np.ones(n_assets, dtype=np.float64)
            edge = np.zeros(n_assets, dtype=np.float64)
        out[t] = constrain_weights(raw, benchmark, sectors, factor_t, previous, edge, box)
        previous = out[t]
    return out


def exposure_violations(
    weights: np.ndarray,
    benchmark: np.ndarray,
    sectors: np.ndarray,
    factors: np.ndarray,
    box: RiskBox,
    *,
    atol: float = 1e-8,
) -> list[str]:
    """Human-readable box breaches. An empty list means the book is inside."""
    w = np.asarray(weights, dtype=np.float64)
    bench = np.asarray(benchmark, dtype=np.float64)
    factor = np.asarray(factors, dtype=np.float64)
    if factor.ndim == 1:
        factor = factor[:, None]
    lo, hi = _bounds(bench, box)
    groups = _sector_groups(sectors)
    reasons: list[str] = []
    if np.any(w < lo - atol) or np.any(w > hi + atol):
        reasons.append("single-name cap")
    active = w - bench
    for idx in groups:
        if abs(float(np.sum(active[idx]))) > box.sector_cap + atol:
            reasons.append("sector cap")
            break
    net = float(np.sum(w))
    if net < box.net_min - atol or net > box.net_max + atol:
        reasons.append("net exposure")
    for k in range(factor.shape[1]):
        if abs(float(active @ factor[:, k])) > box.factor_cap + atol:
            reasons.append("factor exposure")
            break
    return reasons


def _zscore(scores: np.ndarray) -> np.ndarray:
    mu = float(np.mean(scores))
    sd = float(np.std(scores))
    if not np.isfinite(sd) or sd < 1e-12:
        return np.zeros_like(scores)
    return (scores - mu) / sd


def _bounds(benchmark: np.ndarray, box: RiskBox) -> tuple[np.ndarray, np.ndarray]:
    n = benchmark.shape[0]
    if box.mode == "market_neutral":
        lo = np.full(n, -box.name_cap, dtype=np.float64)
        hi = np.full(n, box.name_cap, dtype=np.float64)
    elif box.mode == "index_enhancement":
        lo = benchmark - box.name_cap
        hi = benchmark + box.name_cap
    else:
        lo = np.zeros(n, dtype=np.float64)
        hi = np.ones(n, dtype=np.float64)
    lo = np.maximum(lo, -box.abs_name_cap)
    hi = np.minimum(hi, box.abs_name_cap)
    if np.any(lo > hi + 1e-12):
        raise ValueError("name caps leave an empty interval")
    return lo, hi


def _sector_groups(sectors: np.ndarray) -> tuple[np.ndarray, ...]:
    labels = [str(item) for item in sectors]
    groups: list[np.ndarray] = []
    for name in dict.fromkeys(labels):
        groups.append(np.flatnonzero(np.asarray(labels) == name))
    return tuple(groups)


def _feasible(
    weights: np.ndarray,
    benchmark: np.ndarray,
    groups: tuple[np.ndarray, ...],
    factors: np.ndarray,
    box: RiskBox,
    lo: np.ndarray,
    hi: np.ndarray,
    *,
    atol: float = 1e-8,
) -> bool:
    if np.any(weights < lo - atol) or np.any(weights > hi + atol):
        return False
    active = weights - benchmark
    for idx in groups:
        if abs(float(np.sum(active[idx]))) > box.sector_cap + atol:
            return False
    net = float(np.sum(weights))
    if net < box.net_min - atol or net > box.net_max + atol:
        return False
    for k in range(factors.shape[1]):
        if abs(float(active @ factors[:, k])) > box.factor_cap + atol:
            return False
    return True


def _shift_sum(weights: np.ndarray, idx: np.ndarray, target: float, lo: np.ndarray, hi: np.ndarray) -> None:
    for _ in range(len(idx) + 3):
        gap = target - float(np.sum(weights[idx]))
        if abs(gap) <= 1e-12:
            return
        room = hi[idx] - weights[idx] if gap > 0.0 else weights[idx] - lo[idx]
        room = np.clip(room, 0.0, None)
        total = float(room.sum())
        if total <= 1e-15:
            return
        take = min(abs(gap), total)
        weights[idx] = weights[idx] + np.sign(gap) * take * (room / total)
        np.clip(weights, lo, hi, out=weights)


def _project_once(
    weights: np.ndarray,
    benchmark: np.ndarray,
    groups: tuple[np.ndarray, ...],
    factors: np.ndarray,
    box: RiskBox,
    lo: np.ndarray,
    hi: np.ndarray,
) -> None:
    np.clip(weights, lo, hi, out=weights)
    active = weights - benchmark
    for idx in groups:
        sector_active = float(np.sum(active[idx]))
        clipped = float(np.clip(sector_active, -box.sector_cap, box.sector_cap))
        _shift_sum(weights, idx, float(np.sum(benchmark[idx])) + clipped, lo, hi)
        active = weights - benchmark
    _shift_sum(weights, np.arange(weights.shape[0]), float(np.clip(np.sum(weights), box.net_min, box.net_max)), lo, hi)
    for k in range(factors.shape[1]):
        active = weights - benchmark
        exposure = float(active @ factors[:, k])
        if abs(exposure) <= box.factor_cap + 1e-12 or abs(exposure) <= 1e-15:
            continue
        scale = box.factor_cap / abs(exposure)
        weights[:] = np.clip(benchmark + scale * active, lo, hi)


def _feasible_point(
    raw: np.ndarray,
    benchmark: np.ndarray,
    groups: tuple[np.ndarray, ...],
    factors: np.ndarray,
    box: RiskBox,
    lo: np.ndarray,
    hi: np.ndarray,
) -> np.ndarray:
    for alpha in np.linspace(0.0, 1.0, 21):
        cand = np.clip(benchmark + (1.0 - alpha) * (raw - benchmark), lo, hi)
        for _ in range(12):
            _project_once(cand, benchmark, groups, factors, box, lo, hi)
            if _feasible(cand, benchmark, groups, factors, box, lo, hi):
                return cand
    out = benchmark.copy()
    if not _feasible(out, benchmark, groups, factors, box, lo, hi):
        raise ValueError("risk box has no feasible book")
    return out


def _cost_step(target: np.ndarray, previous: np.ndarray, scores: np.ndarray, box: RiskBox) -> np.ndarray:
    """Full step when the edge pays the one-way cost; otherwise a partial step.

    Both endpoints are feasible and the box is convex, so the blend stays inside.
    ``entry_allowed`` is the desk hurdle (k = 1): predicted gain versus
    fee + half-spread + slippage on the traded notional.
    """
    usable = np.where(np.isfinite(scores), scores, 0.0)
    delta = target - previous
    traded = float(np.sum(np.abs(delta)))
    if traded <= 1e-15:
        return target.copy()
    cost = box.one_way_rate * traded
    edge = float(np.dot(usable, delta))
    if entry_allowed(edge, cost, k=1.0):
        return target.copy()
    if edge <= 0.0 or cost <= 0.0:
        return previous.copy()
    return previous + (edge / cost) * delta
