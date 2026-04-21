"""
Dynamic Delta Hedge Engine — Uniswap V3 LP + Perpetual Futures.

Classes
-------
UniswapV3Position   : Defines a V3 concentrated-liquidity range position.
PerpPosition        : Defines the perpetual-futures short position.
UniswapV3Inventory  : Calculates exact token inventory using V3 √P math.
DeltaHedgeEngine    : Computes net delta and rebalance decision.
TailRiskAnalyzer    : GBM-based probability that price reaches liquidation level.
"""
from __future__ import annotations

import math
import logging
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)


# ── Domain dataclasses ────────────────────────────────────────────────────────

@dataclass(frozen=True)
class UniswapV3Position:
    """Concentrated-liquidity position parameters.

    Attributes
    ----------
    L           : Liquidity units (as returned by the V3 pool).
    price_lower : Lower bound of the position's price range (token1/token0).
    price_upper : Upper bound of the position's price range.
    """
    L: float
    price_lower: float
    price_upper: float

    def __post_init__(self):
        if self.L <= 0:
            raise ValueError("Liquidity L must be positive.")
        if self.price_lower <= 0 or self.price_upper <= 0:
            raise ValueError("Price bounds must be positive.")
        if self.price_lower >= self.price_upper:
            raise ValueError("price_lower must be strictly less than price_upper.")


@dataclass(frozen=True)
class PerpPosition:
    """Perpetual-futures position (short = negative size).

    Attributes
    ----------
    size              : Signed contract size (negative → short).
    entry_price       : Average fill price.
    margin            : Collateral posted (quote asset).
    liquidation_price : Exchange-calculated liquidation trigger price.
    """
    size: float
    entry_price: float
    margin: float
    liquidation_price: float

    def __post_init__(self):
        if self.margin <= 0:
            raise ValueError("Margin must be positive.")
        if self.liquidation_price <= 0:
            raise ValueError("Liquidation price must be positive.")

    @property
    def is_short(self) -> bool:
        return self.size < 0

    @property
    def abs_size(self) -> float:
        return abs(self.size)


@dataclass
class HedgeState:
    """Snapshot of the combined LP + perp portfolio."""
    eth_in_pool: float
    short_size: float
    delta_net: float          # eth_in_pool − short_size  (0 = fully hedged)
    deviation_pct: float      # |delta_net / eth_in_pool| × 100
    current_price: float
    funding_rate_annual: float


@dataclass
class RebalanceDecision:
    """Structured output matching the pseudocode JSON schema.

    Maps to: { ajustar_hedge, novo_tamanho_alvo, justificativa }
    """
    adjust_hedge: bool
    target_short_size: float          # novo_tamanho_alvo
    rationale: str                    # justificativa
    order_side: Optional[str] = None  # "increase_short" | "reduce_short" | None
    order_delta: float = 0.0          # contracts to add/remove
    tail_risk_prob: float = 0.0       # GBM liquidation probability (0–1)


# ── Uniswap V3 Inventory Math ─────────────────────────────────────────────────

class UniswapV3Inventory:
    """
    Calculate the exact amount of the *volatile* asset (token0, e.g. ETH)
    held inside a Uniswap V3 position.

    The V3 invariant in terms of real reserves is:

        x  =  L · (1/√P_current − 1/√P_upper)    if P_lower ≤ P ≤ P_upper
        x  =  L · (1/√P_lower  − 1/√P_upper)     if P < P_lower  (full range)
        x  =  0                                    if P > P_upper  (fully in USDC)
    """

    @staticmethod
    def eth_amount(
        L: float,
        current_price: float,
        price_lower: float,
        price_upper: float,
    ) -> float:
        """Return the ETH (token0) amount in the position at *current_price*.

        Parameters
        ----------
        L             : Uniswap V3 position liquidity.
        current_price : Current pool price (e.g. ETH/USDC).
        price_lower   : Lower tick price bound.
        price_upper   : Upper tick price bound.

        Returns
        -------
        eth : float ≥ 0
        """
        sqrt_current = math.sqrt(current_price)
        sqrt_lower   = math.sqrt(price_lower)
        sqrt_upper   = math.sqrt(price_upper)

        if current_price <= price_lower:
            # All tokens are in the volatile asset (full range)
            eth = L * (1.0 / sqrt_lower - 1.0 / sqrt_upper)
        elif current_price >= price_upper:
            # All tokens are in the stable asset — no ETH exposure
            eth = 0.0
        else:
            # In-range: partial ETH inventory
            eth = L * (1.0 / sqrt_current - 1.0 / sqrt_upper)

        return max(eth, 0.0)

    @staticmethod
    def from_position(position: UniswapV3Position, current_price: float) -> float:
        """Convenience wrapper accepting a `UniswapV3Position` dataclass."""
        return UniswapV3Inventory.eth_amount(
            L=position.L,
            current_price=current_price,
            price_lower=position.price_lower,
            price_upper=position.price_upper,
        )


# ── Tail Risk: GBM Liquidation Probability ────────────────────────────────────

class TailRiskAnalyzer:
    """
    Estimate the probability that the asset price reaches the perpetual
    *liquidation price* within a given horizon.

    Model: Geometric Brownian Motion (risk-neutral / physical log-normal).

        P(t) = P_0 · exp((μ - σ²/2)·t + σ·W(t))

    The first-passage probability for a log-price barrier is approximated via
    Monte Carlo simulation (10 000 paths by default).
    """

    @staticmethod
    def liquidation_probability(
        current_price: float,
        liquidation_price: float,
        volatility_annual: float,
        drift_annual: float = 0.0,
        horizon_hours: float = 8.0,
        n_paths: int = 10_000,
        n_steps: int = 480,
        seed: Optional[int] = 42,
    ) -> dict:
        """
        Returns
        -------
        dict with keys:
            prob          : float — estimated liquidation probability (0-1)
            horizon_hours : float — horizon used
            barrier       : float — liquidation price
            current_price : float
            volatility    : float — annual volatility used
            paths_simulated : int
        """
        rng = np.random.default_rng(seed)

        T = horizon_hours / 8_760.0          # fraction of a year
        dt = T / n_steps
        sqrt_dt = math.sqrt(dt)

        mu    = drift_annual - 0.5 * volatility_annual ** 2
        sigma = volatility_annual

        log_price = np.zeros((n_paths,))     # log(P/P0)
        touched   = np.zeros(n_paths, dtype=bool)

        log_barrier = math.log(liquidation_price / current_price)

        for _ in range(n_steps):
            dW = rng.standard_normal(n_paths) * sqrt_dt
            log_price += mu * dt + sigma * dW

            if liquidation_price > current_price:
                # Short: liquidation if price rises above barrier
                touched |= log_price >= log_barrier
            else:
                # Long: liquidation if price falls below barrier
                touched |= log_price <= log_barrier

        prob = float(np.mean(touched))

        logger.debug(
            "TailRisk: price=%.2f liq=%.2f σ=%.2f T=%.1fh → prob=%.4f",
            current_price, liquidation_price, volatility_annual, horizon_hours, prob,
        )

        return {
            "prob": prob,
            "horizon_hours": horizon_hours,
            "barrier": liquidation_price,
            "current_price": current_price,
            "volatility_annual": volatility_annual,
            "paths_simulated": n_paths,
        }


# ── Delta Hedge Engine ────────────────────────────────────────────────────────

class DeltaHedgeEngine:
    """
    Orchestrates delta-neutral hedging for a Uniswap V3 LP position.

    Parameters
    ----------
    tolerance           : Fractional deviation threshold (default 0.05 = 5%).
    high_funding_threshold : Annualised funding rate above which the
                            tolerance band is widened by `funding_band_multiplier`.
    funding_band_multiplier : How much to widen the tolerance under high funding.
    tail_risk_threshold : GBM probability above which rebalance is forced.
    """

    def __init__(
        self,
        tolerance: float = 0.05,
        high_funding_threshold: float = 0.30,
        funding_band_multiplier: float = 1.5,
        tail_risk_threshold: float = 0.05,
    ):
        self.tolerance              = tolerance
        self.high_funding_threshold = high_funding_threshold
        self.funding_band_multiplier = funding_band_multiplier
        self.tail_risk_threshold    = tail_risk_threshold

    # ── Exposure calculation ──────────────────────────────────────────────────

    def calculate_exposure(
        self,
        lp_position: UniswapV3Position,
        perp_position: PerpPosition,
        current_price: float,
        funding_rate_annual: float = 0.0,
    ) -> HedgeState:
        """
        Step 1 from pseudocode: Calcular_Exposicao_Delta.

        Computes:
            eth_in_pool   = UniswapV3Inventory.from_position(lp, price)
            short_size    = |perp.size|
            delta_net     = eth_in_pool − short_size
            deviation_pct = |delta_net / eth_in_pool| × 100
        """
        eth_in_pool = UniswapV3Inventory.from_position(lp_position, current_price)
        short_size  = perp_position.abs_size

        delta_net = eth_in_pool - short_size

        if eth_in_pool > 0:
            deviation_pct = abs(delta_net / eth_in_pool) * 100
        else:
            # Position is fully in stablecoin — any short is over-hedged
            deviation_pct = 100.0 if short_size > 0 else 0.0

        state = HedgeState(
            eth_in_pool       = eth_in_pool,
            short_size        = short_size,
            delta_net         = delta_net,
            deviation_pct     = deviation_pct,
            current_price     = current_price,
            funding_rate_annual = funding_rate_annual,
        )

        logger.info(
            "Exposure — ETH in pool: %.4f, Short: %.4f, ΔNet: %.4f (%.2f%%)",
            eth_in_pool, short_size, delta_net, deviation_pct,
        )
        return state

    # ── Rebalance decision ────────────────────────────────────────────────────

    def rebalance_decision(
        self,
        state: HedgeState,
        volatility_annual: float = 0.80,
        horizon_hours: float = 8.0,
        perp_position: Optional[PerpPosition] = None,
        n_paths: int = 10_000,
    ) -> RebalanceDecision:
        """
        Steps 2 & 3 from pseudocode: Executar_Rebalanceamento_Hedge + AI prompt.

        Decision logic (in priority order):
        1. **Tail risk override**: if GBM prob(liquidation) > tail_risk_threshold
           → force rebalance regardless of tolerance.
        2. **Funding-adjusted tolerance**: if funding_rate_annual > high_funding_threshold
           → widen tolerance (reduce over-trading cost).
        3. **Deviation check**: if |Δ/eth| > effective_tolerance → rebalance.
        """
        # ── Tail risk ────────────────────────────────────────────────────────
        tail_prob = 0.0
        if perp_position is not None and perp_position.liquidation_price > 0:
            tail = TailRiskAnalyzer.liquidation_probability(
                current_price      = state.current_price,
                liquidation_price  = perp_position.liquidation_price,
                volatility_annual  = volatility_annual,
                horizon_hours      = horizon_hours,
                n_paths            = n_paths,
            )
            tail_prob = tail["prob"]

        forced_by_tail_risk = tail_prob >= self.tail_risk_threshold

        # ── Effective tolerance (widen under high funding) ───────────────────
        effective_tolerance = self.tolerance
        if state.funding_rate_annual > self.high_funding_threshold:
            effective_tolerance *= self.funding_band_multiplier

        deviation_frac = abs(state.delta_net) / state.eth_in_pool if state.eth_in_pool > 0 else 1.0

        # ── Decision ─────────────────────────────────────────────────────────
        should_adjust    = forced_by_tail_risk or (deviation_frac > effective_tolerance)
        target_short     = state.eth_in_pool   # fully hedged = match ETH in pool
        delta            = state.delta_net      # how much to adjust

        if not should_adjust:
            return RebalanceDecision(
                adjust_hedge      = False,
                target_short_size = state.short_size,
                rationale=(
                    f"Desvio de {state.deviation_pct:.2f}% está dentro da "
                    f"tolerância efetiva de {effective_tolerance * 100:.1f}%. "
                    f"Risco de cauda: {tail_prob:.2%}. Nenhuma ação necessária."
                ),
                order_side        = None,
                order_delta       = 0.0,
                tail_risk_prob    = tail_prob,
            )

        if delta > 0:
            # Under-hedged → increase short
            order_side = "increase_short"
            rationale  = (
                f"Delta líquido +{delta:.4f} ETH: posição está subprotegida "
                f"({state.deviation_pct:.2f}% > tolerância {effective_tolerance * 100:.1f}%). "
            )
        else:
            # Over-hedged → reduce short
            order_side = "reduce_short"
            rationale  = (
                f"Delta líquido {delta:.4f} ETH: short maior que inventário na pool "
                f"({state.deviation_pct:.2f}% > tolerância {effective_tolerance * 100:.1f}%). "
            )

        if forced_by_tail_risk:
            rationale += (
                f"FORÇADO por risco de cauda: probabilidade de liquidação "
                f"de {tail_prob:.2%} em {horizon_hours}h excede limiar de "
                f"{self.tail_risk_threshold:.0%}."
            )
        else:
            rationale += f"Risco de cauda: {tail_prob:.2%}."

        logger.info(
            "Rebalance decision — adjust=%s side=%s Δ=%.4f tail_risk=%.4f",
            should_adjust, order_side, abs(delta), tail_prob,
        )

        return RebalanceDecision(
            adjust_hedge      = True,
            target_short_size = target_short,
            rationale         = rationale,
            order_side        = order_side,
            order_delta       = abs(delta),
            tail_risk_prob    = tail_prob,
        )
