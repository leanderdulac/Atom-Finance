"""
Cross-venue perpetual basis calculator.

Takes *already observed* bid/ask/fee/funding per venue. It does not connect to
Hyperliquid, Binance, or any DEX. Net edge is after round-trip taker fees and
one 8h funding period on the short perp. Quotes are assumed to be firm, which
on a perp DEX they are not.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class VenueQuote:
    venue: str
    bid: float
    ask: float
    taker_fee_bps: float
    funding_8h: float = 0.0  # paid by longs if positive


def _buy_cost(q: VenueQuote) -> float:
    return q.ask * (1.0 + q.taker_fee_bps / 10_000.0)


def _sell_proceeds(q: VenueQuote) -> float:
    return q.bid * (1.0 - q.taker_fee_bps / 10_000.0)


def scan(quotes: list[dict], notional: float = 10_000.0) -> dict:
    venues = [VenueQuote(**q) if not isinstance(q, VenueQuote) else q for q in quotes]
    if len(venues) < 2:
        raise ValueError("Need at least two venues")
    for v in venues:
        if v.bid <= 0 or v.ask <= 0 or v.ask < v.bid:
            raise ValueError(f"Invalid book on {v.venue}")

    books = []
    for v in venues:
        mid = 0.5 * (v.bid + v.ask)
        books.append({
            "venue": v.venue,
            "bid": v.bid,
            "ask": v.ask,
            "mid": round(mid, 8),
            "spread_bps": round(1e4 * (v.ask - v.bid) / mid, 3),
            "taker_fee_bps": v.taker_fee_bps,
            "funding_8h": v.funding_8h,
            "effective_buy": round(_buy_cost(v), 8),
            "effective_sell": round(_sell_proceeds(v), 8),
        })

    best = None
    for buy in venues:
        for sell in venues:
            if buy.venue == sell.venue:
                continue
            buy_px = _buy_cost(buy)
            sell_px = _sell_proceeds(sell)
            gross = sell_px / buy_px - 1.0
            # Long the cheap venue, short the rich one: collect funding if the short is on a +funding book.
            funding = sell.funding_8h - buy.funding_8h
            net = gross + funding
            candidate = {
                "buy_venue": buy.venue,
                "sell_venue": sell.venue,
                "gross_edge": round(gross, 8),
                "funding_8h_edge": round(funding, 8),
                "net_edge": round(net, 8),
                "net_edge_bps": round(net * 1e4, 3),
                "pnl_on_notional": round(net * notional, 4),
            }
            if best is None or candidate["net_edge"] > best["net_edge"]:
                best = candidate

    tradable = bool(best and best["net_edge"] > 0)
    return {
        "venues": books,
        "best_route": best,
        "positive_after_fees": tradable,
        "notional": notional,
        "math": (
            "Buy effective = ask·(1+f), sell effective = bid·(1−f). "
            "Net = sell/buy − 1 + (funding_short − funding_long) over one 8h window."
        ),
        "eligible_for_live_trading": False,
        "what_broke": [
            "DEX mids are not firm; the arb disappears in the next block/oracle update.",
            "Ignores gas, inventory, margin, liquidation, and cross-margin haircut.",
            "One 8h funding snapshot is not the funding path over the hold.",
            "Size is a notional scalar — no depth, so this is not a capacity estimate.",
            "This calculator never talks to a chain. Wire a collector before calling it a scanner.",
        ],
    }
