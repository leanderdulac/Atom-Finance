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
                     slippage: float = 0.0005) -> dict:
        if seed is not None:
            np.random.seed(seed)

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
        cost_basis = 0.0  # total cost paid at last buy (including commission)
        for i in range(1, n):
            if signals[i - 1] == 1 and position <= 0 and i < n - 1:  # Buy
                execution_price = prices[i] * (1 + slippage)
                shares = int(capital / (execution_price * (1 + commission)))
                cost = shares * execution_price * (1 + commission)
                if shares > 0 and cost <= capital:
                    traded_notional += shares * execution_price
                    total_costs += cost - shares * prices[i]
                    capital -= cost
                    cost_basis = cost
                    position = 1
                    trades.append({"day": i, "type": "BUY", "price": round(float(execution_price), 2), "shares": shares})
            elif signals[i - 1] == -1 and position > 0:  # Sell
                execution_price = prices[i] * (1 - slippage)
                revenue = shares * execution_price * (1 - commission)
                traded_notional += shares * execution_price
                total_costs += shares * prices[i] - revenue
                capital += revenue
                pnl = revenue - cost_basis
                trades.append({"day": i, "type": "SELL", "price": round(float(execution_price), 2), "shares": shares, "pnl": round(float(pnl), 2)})
                shares = 0
                position = 0
                cost_basis = 0.0

            total_value = capital + shares * prices[i]
            portfolio_values.append(total_value)

        # Close any open position
        if shares > 0:
            execution_price = prices[-1] * (1 - slippage)
            revenue = shares * execution_price * (1 - commission)
            traded_notional += shares * execution_price
            total_costs += shares * prices[-1] - revenue
            capital += revenue
            trades.append({"day": n - 1, "type": "SELL", "reason": "final_liquidation",
                           "price": round(float(execution_price), 2), "shares": shares,
                           "pnl": round(float(revenue - cost_basis), 2)})
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
        metrics["performance"]["turnover_initial_capital"] = round(float(traded_notional / initial_capital), 4)
        metrics["assumptions"] = {"commission": commission, "slippage": slippage,
                                  "benchmark": "buy-and-hold gross, without costs"}
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
        period = params.get("period", 14)
        oversold = params.get("oversold", 30)
        overbought = params.get("overbought", 70)
        n = len(prices)
        signals = np.zeros(n)

        for i in range(period + 1, n):
            changes = np.diff(prices[i - period:i + 1])
            gains = np.mean(changes[changes > 0]) if np.any(changes > 0) else 0
            losses = -np.mean(changes[changes < 0]) if np.any(changes < 0) else 0.001
            rs = gains / max(losses, 0.001)
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

        # Sortino Ratio
        downside_returns = pv_returns[pv_returns < 0]
        downside_std = float(np.std(downside_returns)) if len(downside_returns) > 0 else 0.001
        sortino = float(np.mean(pv_returns) / max(downside_std, 1e-8) * np.sqrt(252))

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
