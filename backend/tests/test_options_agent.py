"""Options agent recommendations are priced, not hardcoded (no network)."""
from app.models.options_agent import OptionsExpert
from app.models.pricing import BlackScholes

T, R, IV = 30.0 / 365.0, 0.10, 0.35


class TestPricedRecommendations:
    def test_bull_spread_matches_bs_legs(self):
        spot = 100.0
        trade = OptionsExpert._recommend_bullish("PETR4", spot, IV)
        k1, k2 = trade.strike, trade.strike_2
        c1 = BlackScholes.price(spot, k1, T, R, IV, "call")
        c2 = BlackScholes.price(spot, k2, T, R, IV, "call")
        assert trade.cost_brl == round(c1 - c2, 2)
        assert trade.max_profit == round((k2 - k1) - (c1 - c2), 2)
        assert trade.max_loss == round(-(c1 - c2), 2)
        g1 = BlackScholes.greeks(spot, k1, T, R, IV, "call")
        g2 = BlackScholes.greeks(spot, k2, T, R, IV, "call")
        assert trade.delta == round(g1.delta - g2.delta, 4)
        assert 0 < trade.prob_success < 100

    def test_bear_spread_matches_bs_legs(self):
        spot = 100.0
        trade = OptionsExpert._recommend_bearish("VALE3", spot, IV)
        k1, k2 = trade.strike, trade.strike_2
        p1 = BlackScholes.price(spot, k1, T, R, IV, "put")
        p2 = BlackScholes.price(spot, k2, T, R, IV, "put")
        assert trade.cost_brl == round(p1 - p2, 2)
        assert trade.max_profit == round((k1 - k2) - (p1 - p2), 2)
        assert 0 < trade.prob_success < 100

    def test_covered_call_is_short_call_plus_stock(self):
        spot, strike = 100.0, 108.0
        trade = OptionsExpert._recommend_income("ITUB4", spot, IV)
        leg = BlackScholes.greeks(spot, strike, T, R, IV, "call")
        assert trade.strike == strike
        assert trade.cost_brl == -round(leg.price, 2)
        assert trade.delta == round(1.0 - leg.delta, 4)
        assert trade.max_loss == round(leg.price - spot, 2)
