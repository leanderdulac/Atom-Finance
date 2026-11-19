"""
Backtesting Engine
- Strategy backtesting with realistic execution
- Performance metrics (Sharpe, Sortino, Calmar, etc.)
- Drawdown analysis
"""

import numpy as np


class BacktestEngine:
    """Simple but comprehensive backtesting engine."""

    @staticmethod
    def run_strategy(prices: np.ndarray, strategy: str = "sma_crossover",
                     params: dict | None = None, initial_capital: float = 100_000,
                     commission: float = 0.001, seed: int | None = 42,
                     slippage: float = 0.0005, *, entry_cost_k: float = 2.0,
                     order_style: str = "market", limit_timeout: int = 5) -> dict:
        # NOTE: seed is accepted for API compatibility but this engine is
        # deterministic (no RNG calls); it intentionally seeds nothing.
        _ = seed

        prices = np.asarray(prices, dtype=np.float64)
        if len(prices) < 2 or not np.all(np.isfinite(prices)) or np.any(prices <= 0):
            raise ValueError("Prices must be positive and finite")
        if not 0 <= commission <= 0.01 or not 0 <= slippage <= 0.01:
            raise ValueError("Invalid transaction costs")
        params = params or {}
        returns = np.diff(prices) / prices[:-1]
        n = len(prices)

        # Generate signals based on strategy
        if strategy == "sma_crossover":
            signals = BacktestEngine._sma_crossover(prices, params)
        elif strategy == "mean_reversion":
            signals = BacktestEngine._mean_reversion(prices, params)
        elif strategy == "momentum":
            signals = BacktestEngine._momentum(prices, params)
        elif strategy == "rsi":
            signals = BacktestEngine._rsi_strategy(prices, params)
        else:
            signals = np.zeros(n)

        # Simulate execution
        capital = initial_capital
        position = 0
        shares = 0
        portfolio_values = [capital]
        trades = []

        traded_notional = 0.0
        total_costs = 0.0
        fee_paid = 0.0
        half_paid = 0.0
        slip_paid = 0.0
        cost_basis = 0.0  # total cost paid at last buy (including commission)
        skipped: list[dict] = []
        pending: dict | None = None
        n_orders = 0
        n_expired = 0
        round_trip = 2.0 * (commission + slippage)
        style = (order_style or "market").lower()
        if style not in ("market", "limit"):
            raise ValueError("order_style must be market or limit")

        def _edge(i: int) -> float:
            """Expected move, as a fraction of price, known at the signal bar."""
            px0 = float(prices[0])
            if strategy == "sma_crossover":
                sw = int(params.get("short_window", 20))
                lw = int(params.get("long_window", 50))
                sig = i - 1
                if sig >= lw - 1 and prices[sig] > 0:
                    sma_s = float(np.mean(prices[sig - sw + 1:sig + 1]))
                    sma_l = float(np.mean(prices[sig - lw + 1:sig + 1]))
                    return abs(sma_s - sma_l) / float(prices[sig])
            elif strategy == "mean_reversion":
                window = int(params.get("window", 20))
                sig = i - 1
                if sig >= window and prices[sig] > 0:
                    mu = float(np.mean(prices[sig - window:sig]))
                    return abs(float(prices[sig]) - mu) / float(prices[sig])
            elif strategy == "momentum":
                lookback = int(params.get("lookback", 20))
                sig = i - 1
                if sig >= lookback and prices[sig - lookback] > 0:
                    return abs(float(prices[sig]) / float(prices[sig - lookback]) - 1.0)
            if px0 > 0:
                return abs(float(prices[i]) / px0 - 1.0)
            return 0.0

        def _components(mid: float, fill_px: float, qty: int, side: str) -> tuple[float, float, float]:
            """Fee on the fill; the old slippage concession split into half-spread and impact.

            Default market fills still execute at mid * (1 ± slippage). The two
            pieces sum to that concession, so transaction_costs is unchanged.
            """
            fee = qty * fill_px * commission
            concession = qty * mid * slippage
            hs_rate = min(0.0002, slippage)
            if slippage > 0:
                half = concession * (hs_rate / slippage)
                impact = concession - half
            else:
                half = 0.0
                impact = 0.0
            if side == "limit":
                # A crossed limit fills at the level: no walk, and the
                # improvement versus mid is spread capture, not a cost.
                improve = (mid - fill_px) if fill_px < mid else (fill_px - mid)
                return fee, 0.0, 0.0 if improve >= 0 else qty * abs(fill_px - mid)
            return fee, half, impact

        def _record(day: int, kind: str, fill_px: float, qty: int, pnl: float | None, side: str) -> None:
            nonlocal traded_notional, total_costs, fee_paid, half_paid, slip_paid, capital, cost_basis
            mid = float(prices[day])
            fee, half, impact = _components(mid, fill_px, qty, side)
            fee_paid += fee
            half_paid += half
            slip_paid += impact
            if kind == "BUY":
                paid = qty * fill_px + fee
                traded_notional += qty * fill_px
                total_costs += paid - qty * mid
                capital -= paid
                cost_basis = paid
            else:
                revenue = qty * fill_px - fee
                traded_notional += qty * fill_px
                total_costs += qty * mid - revenue
                capital += revenue
            row = {
                "day": day, "type": kind, "price": round(float(fill_px), 2), "shares": qty,
                "fee": round(float(fee), 4), "half_spread": round(float(half), 4),
                "slippage": round(float(impact), 4), "liquidity": "maker" if side == "limit" else "taker",
            }
            if pnl is not None:
                row["pnl"] = round(float(pnl), 2)
            trades.append(row)

        for i in range(1, n):
            if pending is not None and position <= 0:
                age = i - int(pending["placed"])
                level = float(pending["level"])
                prev = float(pending["prev"])
                crossed = prev > level >= float(prices[i])
                pending["prev"] = float(prices[i])
                if crossed and age <= limit_timeout and i < n - 1:
                    execution_price = level
                    shares = int(capital / (execution_price * (1 + commission)))
                    cost = shares * execution_price * (1 + commission)
                    if shares > 0 and cost <= capital:
                        _record(i, "BUY", execution_price, shares, None, "limit")
                        position = 1
                    pending = None
                elif age >= limit_timeout or i >= n - 1:
                    n_expired += 1
                    skipped.append({"day": i, "reason": "expired", "level": level})
                    pending = None
            if signals[i - 1] == 1 and position <= 0 and i < n - 1 and pending is None:  # Buy
                edge = _edge(i)
                if entry_cost_k > 0 and edge < entry_cost_k * round_trip:
                    skipped.append({
                        "day": i, "reason": "expected_gain",
                        "expected_gain": round(float(edge), 6),
                        "round_trip_cost": round_trip, "k": entry_cost_k,
                    })
                elif style == "limit":
                    pending = {"placed": i, "level": float(prices[i - 1]), "prev": float(prices[i])}
                    n_orders += 1
                else:
                    execution_price = prices[i] * (1 + slippage)
                    shares = int(capital / (execution_price * (1 + commission)))
                    cost = shares * execution_price * (1 + commission)
                    if shares > 0 and cost <= capital:
                        _record(i, "BUY", float(execution_price), shares, None, "market")
                        position = 1
                        n_orders += 1
            elif signals[i - 1] == -1 and position > 0:  # Sell
                # Sells stay on the market concession, including after a maker
                # entry, so a round trip's cash matches the historical engine.
                execution_price = prices[i] * (1 - slippage)
                revenue = shares * execution_price * (1 - commission)
                pnl = revenue - cost_basis
                _record(i, "SELL", float(execution_price), shares, pnl, "market")
                shares = 0
                position = 0
                cost_basis = 0.0
                n_orders += 1

            total_value = capital + shares * prices[i]
            portfolio_values.append(total_value)

        # Close any open position
        if shares > 0:
            execution_price = float(prices[-1] * (1 - slippage))
            revenue = shares * execution_price * (1 - commission)
            pnl = revenue - cost_basis
            _record(n - 1, "SELL", execution_price, shares, pnl, "market")
            trades[-1]["reason"] = "final_liquidation"
            n_orders += 1
            shares = 0
            position = 0
            portfolio_values[-1] = capital

        portfolio_values = np.array(portfolio_values)

        # Calculate performance metrics
        pv_returns = np.diff(portfolio_values) / portfolio_values[:-1]
        bh_returns = returns  # Buy and hold

        metrics = BacktestEngine._calculate_metrics(portfolio_values, pv_returns, bh_returns, initial_capital)
        metrics["validation"] = {"status": "exploratory_backtest", "eligible_for_live_trading": False,
                                 "out_of_sample": False, "execution_delay_bars": 1,
                                 "note": "Use the ML research protocol for chronological out-of-sample validation."}
        metrics["performance"]["transaction_costs"] = round(float(total_costs), 2)
        metrics["performance"]["fee"] = round(float(fee_paid), 2)
        metrics["performance"]["half_spread"] = round(float(half_paid), 2)
        metrics["performance"]["slippage"] = round(float(slip_paid), 2)
        metrics["performance"]["turnover_initial_capital"] = round(float(traded_notional / initial_capital), 4)
        n_filled = n_orders - n_expired
        metrics["execution"] = {
            "order_style": style,
            "n_orders": n_orders,
            "n_filled": n_filled,
            "n_expired": n_expired,
            "n_unfilled": n_expired,
            "fill_rate": None if n_orders == 0 else round(n_filled / n_orders, 6),
            "n_skipped": len(skipped),
            "skipped_by_reason": {
                reason: sum(1 for row in skipped if row.get("reason") == reason)
                for reason in ("expected_gain", "expired", "spread", "volume")
            },
            "skipped_signals": skipped[:40],
            "entry_cost_k": entry_cost_k,
            "half_spread_source": "estimate",
            "slippage_source": "estimate",
            "flagged_estimate": True,
        }
        metrics["assumptions"] = {
            "commission": commission, "slippage": slippage,
            "entry_cost_k": entry_cost_k, "order_style": style,
            "cost_split": "fee on the fill; slippage concession split into 2 bps half-spread (capped) and the rest as impact",
            "benchmark": "buy-and-hold gross, without costs",
        }
        metrics["trades"] = trades[-50:]
        metrics["n_trades"] = len(trades)
        metrics["strategy"] = strategy
        step = max(1, len(portfolio_values) // 200)
        sampled = [round(float(v), 2) for v in portfolio_values[::step]]
        if sampled[-1] != round(float(portfolio_values[-1]), 2):
            sampled.append(round(float(portfolio_values[-1]), 2))
        bh = initial_capital * prices / prices[0]
        bh_sampled = [round(float(v), 2) for v in bh[::step]]
        if bh_sampled[-1] != round(float(bh[-1]), 2):
            bh_sampled.append(round(float(bh[-1]), 2))
        metrics["portfolio_values"] = sampled
        metrics["buy_hold_values"] = bh_sampled

        return metrics

    @staticmethod
    def _sma_crossover(prices: np.ndarray, params: dict) -> np.ndarray:
        short_window = params.get("short_window", 20)
        long_window = params.get("long_window", 50)
        n = len(prices)
        signals = np.zeros(n)

        for i in range(long_window - 1, n):
            sma_short = np.mean(prices[i - short_window + 1:i + 1])
            sma_long = np.mean(prices[i - long_window + 1:i + 1])
            if sma_short > sma_long:
                signals[i] = 1
            elif sma_short < sma_long:
                signals[i] = -1
        return signals

    @staticmethod
    def _mean_reversion(prices: np.ndarray, params: dict) -> np.ndarray:
        window = params.get("window", 20)
        z_threshold = params.get("z_threshold", 2.0)
        n = len(prices)
        signals = np.zeros(n)

        for i in range(window, n):
            mu = np.mean(prices[i - window:i])
            sigma = np.std(prices[i - window:i])
            z = (prices[i] - mu) / max(sigma, 0.001)
            if z < -z_threshold:
                signals[i] = 1
            elif z > z_threshold:
                signals[i] = -1
        return signals

    @staticmethod
    def _momentum(prices: np.ndarray, params: dict) -> np.ndarray:
        lookback = params.get("lookback", 20)
        n = len(prices)
        signals = np.zeros(n)

        for i in range(lookback, n):
            ret = (prices[i] - prices[i - lookback]) / prices[i - lookback]
            if ret > 0.02:
                signals[i] = 1
            elif ret < -0.02:
                signals[i] = -1
        return signals

    @staticmethod
    def _rsi_strategy(prices: np.ndarray, params: dict) -> np.ndarray:
        """RSI signals with Wilder's RMA smoothing (not a simple mean).

        avg_gain[i] = (avg_gain[i-1] * (n-1) + gain[i]) / n, seeded with the
        SMA of the first `period` deltas — Wilder (1978). A simple rolling
        mean answers a different question and must not be labelled RSI.
        """
        period = params.get("period", 14)
        oversold = params.get("oversold", 30)
        overbought = params.get("overbought", 70)
        n = len(prices)
        signals = np.zeros(n)
        if n <= period + 1:
            return signals

        deltas = np.diff(prices)
        gains = np.where(deltas > 0, deltas, 0.0)
        losses = np.where(deltas < 0, -deltas, 0.0)
        avg_gain = np.zeros(n)
        avg_loss = np.zeros(n)
        avg_gain[period] = float(np.mean(gains[:period]))
        avg_loss[period] = float(np.mean(losses[:period]))
        for i in range(period + 1, n):
            avg_gain[i] = (avg_gain[i - 1] * (period - 1) + gains[i - 1]) / period
            avg_loss[i] = (avg_loss[i - 1] * (period - 1) + losses[i - 1]) / period

        for i in range(period + 1, n):
            if avg_loss[i] == 0:
                rsi = 100.0 if avg_gain[i] > 0 else 50.0
            else:
                rs = avg_gain[i] / avg_loss[i]
                rsi = 100 - (100 / (1 + rs))
            if rsi < oversold:
                signals[i] = 1
            elif rsi > overbought:
                signals[i] = -1
        return signals

    @staticmethod
    def _calculate_metrics(portfolio_values: np.ndarray, pv_returns: np.ndarray,
                           bh_returns: np.ndarray, initial_capital: float) -> dict:
        total_return = (portfolio_values[-1] / initial_capital - 1) * 100
        bh_total_return = (np.prod(1 + bh_returns) - 1) * 100

        # Annualized metrics
        n_days = len(pv_returns)
        ann_factor = 252 / max(n_days, 1)

        ann_return = ((1 + total_return / 100) ** ann_factor - 1) * 100
        ann_vol = float(np.std(pv_returns) * np.sqrt(252) * 100)

        # Sharpe Ratio
        sharpe = float(np.mean(pv_returns) / max(np.std(pv_returns), 1e-8) * np.sqrt(252))

        # Sortino: downside deviation = sqrt(E[min(r,0)²]), not std of negative days only.
        downside_dev = float(np.sqrt(np.mean(np.minimum(pv_returns, 0.0) ** 2)))
        sortino = float(np.mean(pv_returns) / max(downside_dev, 1e-8) * np.sqrt(252))

        # Maximum Drawdown
        running_max = np.maximum.accumulate(portfolio_values)
        drawdowns = (portfolio_values - running_max) / running_max
        max_drawdown = float(np.min(drawdowns) * 100)

        # Calmar Ratio
        calmar = ann_return / abs(max_drawdown) if max_drawdown != 0 else 0

        # Win rate
        winning_days = np.sum(pv_returns > 0)
        win_rate = float(winning_days / max(len(pv_returns), 1) * 100)

        return {
            "performance": {
                "total_return_pct": round(total_return, 2),
                "buy_hold_return_pct": round(bh_total_return, 2),
                "alpha": round(total_return - bh_total_return, 2),
                "annualized_return_pct": round(ann_return, 2),
                "annualized_volatility_pct": round(ann_vol, 2),
                "sharpe_ratio": round(sharpe, 4),
                "sortino_ratio": round(sortino, 4),
                "calmar_ratio": round(calmar, 4),
                "max_drawdown_pct": round(max_drawdown, 2),
                "win_rate_pct": round(win_rate, 2),
                "final_value": round(float(portfolio_values[-1]), 2),
            },
        }
