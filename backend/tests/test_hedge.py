"""Tests for the Dynamic Hedge module (models only — no HTTP)."""
from __future__ import annotations

import math
import pytest

from app.models.hedge import (
    DeltaHedgeEngine,
    PerpPosition,
    TailRiskAnalyzer,
    UniswapV3Inventory,
    UniswapV3Position,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def lp_position():
    """ETH/USDC position with range [1800, 2400] and liquidity L=15_000."""
    return UniswapV3Position(L=15_000, price_lower=1_800, price_upper=2_400)


@pytest.fixture
def short_perp():
    """Short perpetual position of 5.2 ETH with comfortable margin."""
    return PerpPosition(size=-5.2, entry_price=2_100, margin=10_000, liquidation_price=2_800)


@pytest.fixture
def engine():
    return DeltaHedgeEngine(tolerance=0.05)


# ── UniswapV3Inventory ────────────────────────────────────────────────────────

class TestUniswapV3Inventory:
    def test_price_below_range_returns_max_eth(self, lp_position):
        """When price < lower bound, all liquidity is in ETH (max exposure)."""
        eth = UniswapV3Inventory.from_position(lp_position, current_price=1_500)
        eth_max = UniswapV3Inventory.eth_amount(
            lp_position.L, lp_position.price_lower, lp_position.price_lower, lp_position.price_upper
        )
        assert eth == pytest.approx(eth_max, rel=1e-6)
        assert eth > 0

    def test_price_above_range_returns_zero(self, lp_position):
        """When price > upper bound, position is 100% stablecoin — zero ETH."""
        eth = UniswapV3Inventory.from_position(lp_position, current_price=2_500)
        assert eth == 0.0

    def test_price_in_range_partial_eth(self, lp_position):
        """When price is inside the range, ETH is between 0 and maximum."""
        eth_below = UniswapV3Inventory.from_position(lp_position, current_price=1_500)
        eth_mid   = UniswapV3Inventory.from_position(lp_position, current_price=2_100)
        eth_above = UniswapV3Inventory.from_position(lp_position, current_price=2_500)
        assert 0 < eth_mid < eth_below
        assert eth_mid > eth_above

    def test_eth_monotonically_decreasing_with_price(self, lp_position):
        """Higher price inside range → less ETH (monotonic)."""
        prices = [1_850, 1_950, 2_050, 2_150, 2_250, 2_350]
        eths   = [UniswapV3Inventory.from_position(lp_position, p) for p in prices]
        for i in range(len(eths) - 1):
            assert eths[i] > eths[i + 1], "ETH should decrease as price rises."

    def test_eth_non_negative(self, lp_position):
        """ETH inventory is never negative."""
        for price in [100, 1_800, 2_100, 2_400, 5_000]:
            assert UniswapV3Inventory.from_position(lp_position, price) >= 0

    def test_invalid_L_raises(self):
        with pytest.raises(ValueError):
            UniswapV3Position(L=0, price_lower=1_800, price_upper=2_400)

    def test_invalid_price_range_raises(self):
        with pytest.raises(ValueError):
            UniswapV3Position(L=10_000, price_lower=2_400, price_upper=1_800)

    def test_v3_formula_manual(self):
        """Verify formula against hand-calculated value."""
        L, P, P_upper = 10_000, 2_000, 2_500
        sqrt_P      = math.sqrt(P)
        sqrt_upper  = math.sqrt(P_upper)
        expected    = L * (1.0 / sqrt_P - 1.0 / sqrt_upper)
        result      = UniswapV3Inventory.eth_amount(L, P, 1_500, P_upper)
        assert result == pytest.approx(expected, rel=1e-9)


# ── DeltaHedgeEngine — exposure ───────────────────────────────────────────────

class TestDeltaExposure:
    def test_fully_hedged_zero_delta(self, engine, lp_position):
        """When short exactly equals ETH in pool, delta_net ≈ 0."""
        price = 2_100
        eth   = UniswapV3Inventory.from_position(lp_position, price)
        perp  = PerpPosition(size=-eth, entry_price=price, margin=10_000, liquidation_price=2_800)
        state = engine.calculate_exposure(lp_position, perp, price)
        assert abs(state.delta_net) < 1e-9
        assert state.deviation_pct == pytest.approx(0.0, abs=1e-6)

    def test_under_hedged_positive_delta(self, engine, lp_position, short_perp):
        """Short smaller than ETH in pool → positive (unprotected) delta."""
        price = 2_100
        eth   = UniswapV3Inventory.from_position(lp_position, price)
        perp  = PerpPosition(size=-eth * 0.9, entry_price=price, margin=10_000, liquidation_price=2_800)
        state = engine.calculate_exposure(lp_position, perp, price)
        assert state.delta_net > 0

    def test_over_hedged_negative_delta(self, engine, lp_position):
        """Short larger than ETH in pool → negative delta."""
        price = 2_100
        eth   = UniswapV3Inventory.from_position(lp_position, price)
        perp  = PerpPosition(size=-eth * 1.1, entry_price=price, margin=10_000, liquidation_price=2_800)
        state = engine.calculate_exposure(lp_position, perp, price)
        assert state.delta_net < 0

    def test_price_above_range_zero_eth_pool(self, engine, lp_position):
        """When price above range, eth_in_pool = 0 → deviation = 100%."""
        perp  = PerpPosition(size=-3.0, entry_price=2_500, margin=10_000, liquidation_price=3_000)
        state = engine.calculate_exposure(lp_position, perp, current_price=2_500)
        assert state.eth_in_pool == 0.0
        assert state.deviation_pct == 100.0


# ── DeltaHedgeEngine — rebalance decision ────────────────────────────────────

class TestRebalanceDecision:
    def test_no_adjust_when_within_tolerance(self, engine, lp_position):
        """Delta within 5% → no rebalance."""
        price = 2_100
        eth   = UniswapV3Inventory.from_position(lp_position, price)
        # 2% deviation — inside 5% threshold
        perp  = PerpPosition(size=-eth * 0.98, entry_price=price, margin=50_000, liquidation_price=3_500)
        state = engine.calculate_exposure(lp_position, perp, price)
        decision = engine.rebalance_decision(state, volatility_annual=0.80, perp_position=perp, n_paths=1_000)
        assert decision.adjust_hedge is False
        assert decision.order_delta == 0.0

    def test_adjust_when_over_tolerance(self, engine, lp_position):
        """Delta > 5% → rebalance required."""
        price = 2_100
        eth   = UniswapV3Inventory.from_position(lp_position, price)
        # 20% deviation — outside 5% threshold
        perp  = PerpPosition(size=-eth * 0.80, entry_price=price, margin=50_000, liquidation_price=3_500)
        state = engine.calculate_exposure(lp_position, perp, price)
        decision = engine.rebalance_decision(state, volatility_annual=0.80, perp_position=perp, n_paths=1_000)
        assert decision.adjust_hedge is True
        assert decision.order_side == "increase_short"
        assert decision.order_delta > 0

    def test_reduce_short_when_over_hedged(self, engine, lp_position):
        """Over-hedged short → reduce_short order."""
        price = 2_100
        eth   = UniswapV3Inventory.from_position(lp_position, price)
        perp  = PerpPosition(size=-eth * 1.20, entry_price=price, margin=50_000, liquidation_price=1_000)
        state = engine.calculate_exposure(lp_position, perp, price)
        decision = engine.rebalance_decision(state, volatility_annual=0.80, perp_position=perp, n_paths=1_000)
        assert decision.adjust_hedge is True
        assert decision.order_side == "reduce_short"

    def test_high_funding_widens_tolerance(self, lp_position):
        """High funding rate (50% APR) widens band → borderline case stays quiet."""
        engine_wide = DeltaHedgeEngine(
            tolerance=0.05,
            high_funding_threshold=0.30,
            funding_band_multiplier=1.5,  # effective = 7.5%
        )
        price = 2_100
        eth   = UniswapV3Inventory.from_position(lp_position, price)
        # 6% deviation (within widened 7.5% band, outside base 5%)
        perp  = PerpPosition(size=-eth * 0.94, entry_price=price, margin=50_000, liquidation_price=3_500)
        state = engine_wide.calculate_exposure(lp_position, perp, price, funding_rate_annual=0.50)
        decision = engine_wide.rebalance_decision(state, volatility_annual=0.80, perp_position=perp, n_paths=1_000)
        assert decision.adjust_hedge is False, "Wide band should absorb 6% deviation under high funding."

    def test_tail_risk_forces_rebalance(self, lp_position):
        """Liquidation price very close to current price → tail risk forces rebalance."""
        engine_strict = DeltaHedgeEngine(tolerance=0.05, tail_risk_threshold=0.01)
        price = 2_100
        eth   = UniswapV3Inventory.from_position(lp_position, price)
        # 2% deviation — normally wouldn't rebalance
        perp = PerpPosition(
            size=-eth * 0.98,
            entry_price=price,
            margin=1_000,
            liquidation_price=2_200,  # very close to current → high tail risk
        )
        state    = engine_strict.calculate_exposure(lp_position, perp, price)
        decision = engine_strict.rebalance_decision(
            state, volatility_annual=2.0, horizon_hours=8.0, perp_position=perp, n_paths=5_000
        )
        # With 100% annual vol and liq at +4.7%, probability should be non-trivial
        assert decision.tail_risk_prob > 0.0

    def test_target_size_equals_eth_in_pool(self, engine, lp_position):
        """Rebalance target is always the current ETH in pool (delta-neutral)."""
        price = 2_100
        eth   = UniswapV3Inventory.from_position(lp_position, price)
        perp  = PerpPosition(size=-eth * 0.70, entry_price=price, margin=50_000, liquidation_price=3_500)
        state = engine.calculate_exposure(lp_position, perp, price)
        decision = engine.rebalance_decision(state, perp_position=perp, n_paths=1_000)
        assert decision.target_short_size == pytest.approx(eth, rel=1e-6)


# ── TailRiskAnalyzer ──────────────────────────────────────────────────────────

class TestTailRiskAnalyzer:
    def test_output_keys_present(self):
        result = TailRiskAnalyzer.liquidation_probability(
            current_price=2_000, liquidation_price=2_500,
            volatility_annual=0.80, n_paths=1_000,
        )
        for key in ("prob", "horizon_hours", "barrier", "current_price", "volatility_annual", "paths_simulated"):
            assert key in result

    def test_probability_zero_when_barrier_unreachable(self):
        """Barrier 10× current price with low vol → prob ≈ 0."""
        result = TailRiskAnalyzer.liquidation_probability(
            current_price=2_000, liquidation_price=20_000,
            volatility_annual=0.05, horizon_hours=1.0, n_paths=2_000,
        )
        assert result["prob"] < 0.01

    def test_probability_high_when_barrier_nearby_high_vol(self):
        """Barrier +5% away with 200% annual vol → significant probability."""
        result = TailRiskAnalyzer.liquidation_probability(
            current_price=2_000, liquidation_price=2_100,
            volatility_annual=2.0, horizon_hours=8.0, n_paths=5_000,
        )
        assert result["prob"] > 0.30

    def test_probability_in_valid_range(self):
        """Probability must always be in [0, 1]."""
        for vol in [0.20, 0.80, 2.0]:
            result = TailRiskAnalyzer.liquidation_probability(
                current_price=2_000, liquidation_price=2_500,
                volatility_annual=vol, n_paths=1_000,
            )
            assert 0.0 <= result["prob"] <= 1.0

    def test_higher_vol_higher_prob(self):
        """Higher volatility → higher liquidation probability (all else equal)."""
        low_vol  = TailRiskAnalyzer.liquidation_probability(2_000, 2_400, 0.2, n_paths=5_000)["prob"]
        high_vol = TailRiskAnalyzer.liquidation_probability(2_000, 2_400, 1.5, n_paths=5_000)["prob"]
        assert high_vol > low_vol

    def test_deterministic_with_seed(self):
        """Same seed → identical result."""
        r1 = TailRiskAnalyzer.liquidation_probability(2_000, 2_500, 0.80, seed=7, n_paths=2_000)
        r2 = TailRiskAnalyzer.liquidation_probability(2_000, 2_500, 0.80, seed=7, n_paths=2_000)
        assert r1["prob"] == r2["prob"]
