"""
Avellaneda & Stoikov (2008) high-touch market making.

Reservation price and optimal spread for a CARA dealer facing exponential
intensity λ(δ) = A exp(−k δ). Inventory is simulated with independent Poisson
arrivals on each side. This is the closed-form approximation in the paper, not
the full HJB numerical solution, and it assumes a Brownian mid with constant σ.
"""

from __future__ import annotations

import numpy as np


def avellaneda_stoikov_quotes(
    mid: float,
    inventory: float,
    sigma: float,
    gamma: float,
    k: float,
    A: float,
    time_remaining: float,
) -> dict:
    if mid <= 0 or sigma < 0 or gamma <= 0 or k <= 0 or A <= 0:
        raise ValueError("mid, gamma, k, A must be positive; sigma ≥ 0")
    tau = max(float(time_remaining), 0.0)
    reservation = mid - inventory * gamma * sigma ** 2 * tau
    spread = gamma * sigma ** 2 * tau + (2.0 / gamma) * np.log(1.0 + gamma / k)
    bid = reservation - spread / 2.0
    ask = reservation + spread / 2.0
    delta_bid = mid - bid
    delta_ask = ask - mid
    lambda_bid = A * np.exp(-k * max(delta_bid, 0.0))
    lambda_ask = A * np.exp(-k * max(delta_ask, 0.0))
    return {
        "mid": round(float(mid), 6),
        "inventory": round(float(inventory), 6),
        "reservation_price": round(float(reservation), 6),
        "optimal_spread": round(float(spread), 6),
        "bid": round(float(bid), 6),
        "ask": round(float(ask), 6),
        "delta_bid": round(float(delta_bid), 6),
        "delta_ask": round(float(delta_ask), 6),
        "intensity_bid": round(float(lambda_bid), 6),
        "intensity_ask": round(float(lambda_ask), 6),
        "time_remaining": tau,
        "math": (
            "r = s − q γ σ² (T−t);  δ^a+δ^b = γ σ² (T−t) + (2/γ) ln(1+γ/k). "
            "Quotes are symmetric around the reservation price, not the mid."
        ),
        "what_broke": [
            "Constant σ and exponential intensity are the paper's closed form, not a fitted LOB.",
            "No queue position, no adverse selection beyond the inventory penalty, no latency.",
            "CARA + terminal penalty make the dealer flatten into T; a 24/7 perp book has no T.",
            "A and k are free intensity parameters — they dominate PnL and are usually unidentified.",
        ],
    }


def simulate_inventory(
    mid0: float,
    sigma: float,
    gamma: float,
    k: float,
    A: float,
    T: float,
    n_steps: int = 390,
    q_max: float = 10.0,
    seed: int | None = 42,
) -> dict:
    """Euler mid + Poisson fills. Terminal inventory is penalised, not hedged."""
    if seed is not None:
        np.random.seed(seed)
    dt = T / n_steps
    mid = mid0
    q = 0.0
    cash = 0.0
    mids = [mid]
    qs = [q]
    pnls = [0.0]
    fills = 0
    for step in range(n_steps):
        tau = T - step * dt
        quotes = avellaneda_stoikov_quotes(mid, q, sigma, gamma, k, A, tau)
        if abs(q) >= q_max:
            # Hard inventory cap: pull the overflowing side.
            if q > 0:
                quotes["intensity_bid"] = 0.0
            else:
                quotes["intensity_ask"] = 0.0
        buy_hit = np.random.random() < quotes["intensity_bid"] * dt
        sell_hit = np.random.random() < quotes["intensity_ask"] * dt
        if buy_hit:
            cash -= quotes["bid"]
            q += 1.0
            fills += 1
        if sell_hit:
            cash += quotes["ask"]
            q -= 1.0
            fills += 1
        mid *= np.exp(-0.5 * sigma ** 2 * dt + sigma * np.sqrt(dt) * np.random.standard_normal())
        mids.append(float(mid))
        qs.append(float(q))
        pnls.append(float(cash + q * mid))

    terminal = cash + q * mid
    step = max(1, n_steps // 80)
    return {
        "terminal_pnl": round(float(terminal), 4),
        "terminal_inventory": round(float(q), 4),
        "fills": fills,
        "final_mid": round(float(mid), 6),
        "sample_mid": [round(v, 4) for v in mids[::step]],
        "sample_inventory": [round(v, 4) for v in qs[::step]],
        "sample_pnl": [round(v, 4) for v in pnls[::step]],
        "eligible_for_live_trading": False,
        "what_broke": avellaneda_stoikov_quotes(mid0, 0, sigma, gamma, k, A, T)["what_broke"] + [
            "Independent Poisson fills ignore that a moving mid changes who is at the front of the queue.",
            "Unit inventory per fill is a share-count toy; crypto perps trade in contracts with fees/funding.",
        ],
    }
