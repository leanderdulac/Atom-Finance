"""
Ghost Liquidity Analysis
Measures the difference between consolidated measured liquidity and real tradable
liquidity in fragmented markets, considering HFT impacts and duplicate order cancellations.
"""
import numpy as np
from typing import Optional
from dataclasses import dataclass


@dataclass
class OrderBookLevel:
    price: float
    quantity: float
    venue: str
    is_genuine: bool = True


class GhostLiquidityAnalyzer:
    """
    Ghost Liquidity Detection Engine.
    Analyzes order book depth to identify phantom liquidity caused by:
    - Duplicate orders across multiple venues
    - HFT spoofing/layering
    - Flickering quotes
    """

    @staticmethod
    def analyze_order_book(
        bids: list[dict], asks: list[dict],
        venues: list[str] = None,
        hft_cancel_rate: float = 0.7,
        cross_venue_duplication: float = 0.3,
        seed: Optional[int] = 42
    ) -> dict:
        """
        Analyze order book for ghost liquidity.

        bids/asks: [{"price": 100.0, "quantity": 500, "venue": "CBOE"}]
        """
        if seed is not None:
            np.random.seed(seed)

        if not bids or not asks:
            # Generate synthetic order book for demo
            mid_price = 100.0
            bids, asks = GhostLiquidityAnalyzer._generate_synthetic_book(mid_price, seed)

        # Calculate consolidated liquidity
        total_bid_liquidity = sum(b["quantity"] for b in bids)
        total_ask_liquidity = sum(a["quantity"] for a in asks)
        consolidated_liquidity = total_bid_liquidity + total_ask_liquidity

        # Estimate ghost liquidity components
        # 1. Cross-venue duplication
        venue_groups = {}
        for order in bids + asks:
            venue = order.get("venue", "unknown")
            price = round(order["price"], 2)
            key = f"{price}_{venue}"
            if key not in venue_groups:
                venue_groups[key] = 0
            venue_groups[key] += order["quantity"]

        # Estimate duplicates across venues at same price levels
        price_levels = {}
        for order in bids + asks:
            price = round(order["price"], 2)
            if price not in price_levels:
                price_levels[price] = {"venues": set(), "total_qty": 0}
            price_levels[price]["venues"].add(order.get("venue", "unknown"))
            price_levels[price]["total_qty"] += order["quantity"]

        duplicate_qty = 0
        for level in price_levels.values():
            if len(level["venues"]) > 1:
                duplicate_qty += level["total_qty"] * cross_venue_duplication

        # 2. HFT phantom liquidity (orders likely to be cancelled before execution)
        hft_phantom = consolidated_liquidity * hft_cancel_rate * 0.4

        # 3. Flickering quotes
        flicker_factor = 0.15
        flickering_qty = consolidated_liquidity * flicker_factor

        # Real tradable liquidity
        ghost_total = duplicate_qty + hft_phantom + flickering_qty
        real_liquidity = max(consolidated_liquidity - ghost_total, consolidated_liquidity * 0.1)
        ghost_ratio = ghost_total / consolidated_liquidity if consolidated_liquidity > 0 else 0

        # Depth analysis by level
        bid_prices = sorted(set(b["price"] for b in bids), reverse=True)[:10]
        ask_prices = sorted(set(a["price"] for a in asks))[:10]

        depth_analysis = {
            "bids": [
                {
                    "price": p,
                    "consolidated_qty": sum(b["quantity"] for b in bids if b["price"] == p),
                    "estimated_real_qty": round(sum(b["quantity"] for b in bids if b["price"] == p) * (1 - ghost_ratio), 0),
                }
                for p in bid_prices
            ],
            "asks": [
                {
                    "price": p,
                    "consolidated_qty": sum(a["quantity"] for a in asks if a["price"] == p),
                    "estimated_real_qty": round(sum(a["quantity"] for a in asks if a["price"] == p) * (1 - ghost_ratio), 0),
                }
                for p in ask_prices
            ],
        }

        # Spread analysis
        best_bid = max(b["price"] for b in bids)
        best_ask = min(a["price"] for a in asks)
        spread = best_ask - best_bid
        mid_price = (best_bid + best_ask) / 2

        return {
            "consolidated_liquidity": round(consolidated_liquidity, 0),
            "estimated_real_liquidity": round(real_liquidity, 0),
            "ghost_liquidity": round(ghost_total, 0),
            "ghost_ratio": round(ghost_ratio, 4),
            "ghost_components": {
                "cross_venue_duplicates": round(duplicate_qty, 0),
                "hft_phantom": round(hft_phantom, 0),
                "flickering_quotes": round(flickering_qty, 0),
            },
            "market_quality": {
                "best_bid": round(best_bid, 2),
                "best_ask": round(best_ask, 2),
                "spread": round(spread, 4),
                "spread_bps": round(spread / mid_price * 10000, 2),
                "mid_price": round(mid_price, 2),
            },
            "depth_analysis": depth_analysis,
            "liquidity_score": round((1 - ghost_ratio) * 100, 1),
            "risk_level": "HIGH" if ghost_ratio > 0.6 else ("MEDIUM" if ghost_ratio > 0.3 else "LOW"),
        }

    @staticmethod
    def _generate_synthetic_book(mid_price: float = 100.0, seed: Optional[int] = 42) -> tuple:
        if seed is not None:
            np.random.seed(seed)

        venues = ["CBOE", "NYSE", "NASDAQ", "BATS", "IEX"]
        bids = []
        asks = []

        for i in range(20):
            for venue in np.random.choice(venues, size=np.random.randint(1, 4), replace=False):
                bids.append({
                    "price": round(mid_price - 0.01 * (i + 1), 2),
                    "quantity": int(np.random.exponential(500)),
                    "venue": str(venue),
                })
                asks.append({
                    "price": round(mid_price + 0.01 * (i + 1), 2),
                    "quantity": int(np.random.exponential(500)),
                    "venue": str(venue),
                })

        return bids, asks

    @staticmethod
    def monitor_liquidity_over_time(n_snapshots: int = 100, seed: Optional[int] = 42) -> dict:
        """Simulate liquidity monitoring over time."""
        if seed is not None:
            np.random.seed(seed)

        timestamps = list(range(n_snapshots))
        ghost_ratios = []
        real_liquidity = []
        consolidated = []

        base_liquidity = 50000
        base_ghost = 0.35

        for t in timestamps:
            # Simulate intraday patterns
            hour_factor = 1 + 0.3 * np.sin(2 * np.pi * t / n_snapshots)
            noise = np.random.normal(0, 0.05)

            total = base_liquidity * hour_factor * (1 + noise)
            ghost = base_ghost + 0.1 * np.sin(4 * np.pi * t / n_snapshots) + noise * 0.15
            ghost = np.clip(ghost, 0.1, 0.9)

            consolidated.append(round(float(total), 0))
            real_liquidity.append(round(float(total * (1 - ghost)), 0))
            ghost_ratios.append(round(float(ghost), 4))

        return {
            "timestamps": timestamps,
            "consolidated_liquidity": consolidated,
            "real_liquidity": real_liquidity,
            "ghost_ratios": ghost_ratios,
            "average_ghost_ratio": round(float(np.mean(ghost_ratios)), 4),
            "max_ghost_ratio": round(float(np.max(ghost_ratios)), 4),
        }
