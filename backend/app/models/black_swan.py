"""
Tail-risk diagnostics on a realised return series.

Scope: distribution statistics (skew, excess kurtosis, sigma-exceedance counts,
Hill tail index, max drawdown) and a rolling-volatility change flag. This is not
a regime model — see `app/models/regime.py` for the percentile classifier.
"""
import math

import numpy as np


class BlackSwanDetector:
    """
    Tail-risk diagnostics computed from returns:
    1. Distribution shape vs the Gaussian benchmark (fat tails, skew)
    2. Rolling-volatility shifts
    """

    @staticmethod
    def _finite_float(value: float, default: float = 0.0) -> float:
        value = float(value)
        return value if math.isfinite(value) else default

    @staticmethod
    def analyze_tail_risk(returns: np.ndarray) -> dict:
        """Analyze distribution for tail risk indicators."""
        returns = np.asarray(returns, dtype=np.float64)
        mu = float(np.mean(returns))
        sigma = float(np.std(returns))
        safe_sigma = max(sigma, 1e-12)

        # Kurtosis (excess) - normal = 0, fat tails > 0
        n = len(returns)
        m4 = np.mean((returns - mu)**4)
        kurtosis = float(m4 / safe_sigma**4 - 3)

        # Skewness
        m3 = np.mean((returns - mu)**3)
        skewness = float(m3 / safe_sigma**3)

        # Tail analysis
        z_scores = (returns - mu) / safe_sigma
        extreme_neg = float(np.sum(z_scores < -3) / n * 100)  # Beyond 3 sigma
        extreme_pos = float(np.sum(z_scores > 3) / n * 100)
        extreme_4sig = float(np.sum(np.abs(z_scores) > 4) / n * 100)

        # Expected vs actual extreme events (normal distribution)
        expected_3sig = 0.27  # % for normal
        tail_ratio = float((extreme_neg + extreme_pos) / expected_3sig) if expected_3sig > 0 else 0.0

        # Maximum drawdown
        cumulative = np.cumprod(1 + returns)
        running_max = np.maximum.accumulate(cumulative)
        drawdowns = (cumulative - running_max) / running_max
        max_drawdown = float(np.min(drawdowns))

        # Hill estimator for tail index
        sorted_returns = np.sort(np.abs(returns))[::-1]
        k = max(int(n * 0.05), 5)
        top_k = sorted_returns[:k]
        if top_k[-1] > 0:
            hill_estimator = float(np.mean(np.log(top_k / top_k[-1])))
            tail_index = 1 / hill_estimator if hill_estimator > 0 else 1_000_000.0
        else:
            tail_index = 1_000_000.0

        tail_index = BlackSwanDetector._finite_float(tail_index, 1_000_000.0)

        # Black swan probability score (0-100)
        swan_score = min(100, max(0,
            20 * (kurtosis / 3) +
            15 * abs(skewness) +
            25 * (tail_ratio / 5) +
            20 * abs(max_drawdown) * 10 +
            20 * (1 / max(tail_index, 0.1)) * 5
        ))
        swan_score = BlackSwanDetector._finite_float(swan_score)

        return {
            "statistics": {
                "mean": round(BlackSwanDetector._finite_float(mu * 252 * 100), 2),
                "std_annualized": round(BlackSwanDetector._finite_float(sigma * np.sqrt(252) * 100), 2),
                "skewness": round(BlackSwanDetector._finite_float(skewness), 4),
                "excess_kurtosis": round(BlackSwanDetector._finite_float(kurtosis), 4),
            },
            "tail_analysis": {
                "events_beyond_3sigma_pct": round(BlackSwanDetector._finite_float(extreme_neg + extreme_pos), 4),
                "events_beyond_4sigma_pct": round(BlackSwanDetector._finite_float(extreme_4sig), 4),
                "expected_3sigma_normal_pct": expected_3sig,
                "tail_ratio": round(BlackSwanDetector._finite_float(tail_ratio), 2),
                "hill_tail_index": round(BlackSwanDetector._finite_float(tail_index, 1_000_000.0), 4),
            },
            "risk_metrics": {
                "max_drawdown_pct": round(BlackSwanDetector._finite_float(max_drawdown * 100), 2),
                "worst_day_pct": round(BlackSwanDetector._finite_float(float(np.min(returns)) * 100), 2),
                "best_day_pct": round(BlackSwanDetector._finite_float(float(np.max(returns)) * 100), 2),
            },
            "black_swan_score": round(swan_score, 1),
            "risk_level": "CRITICAL" if swan_score > 75 else ("HIGH" if swan_score > 50 else ("MODERATE" if swan_score > 25 else "LOW")),
        }

    @staticmethod
    def detect_regime_change(returns: np.ndarray, window: int = 60) -> dict:
        """Detect volatility regime changes that may precede black swans."""
        returns = np.asarray(returns, dtype=np.float64)
        n = len(returns)

        if n < window * 2:
            window = n // 4

        rolling_vol = []
        rolling_mean = []
        regime_changes = []

        for i in range(window, n):
            vol = np.std(returns[i - window:i]) * np.sqrt(252)
            mean_r = np.mean(returns[i - window:i]) * 252
            rolling_vol.append(round(float(vol), 4))
            rolling_mean.append(round(float(mean_r), 4))

            if len(rolling_vol) > 1:
                vol_change = abs(rolling_vol[-1] - rolling_vol[-2]) / max(rolling_vol[-2], 0.001)
                if vol_change > 0.15:  # 15% change in vol
                    regime_changes.append({
                        "index": i,
                        "vol_before": rolling_vol[-2],
                        "vol_after": rolling_vol[-1],
                        "change_pct": round(vol_change * 100, 2),
                        "type": "vol_spike" if rolling_vol[-1] > rolling_vol[-2] else "vol_compression",
                    })

        return {
            "rolling_volatility": rolling_vol,
            "rolling_mean_return": rolling_mean,
            "regime_changes": regime_changes[-20:],
            "current_regime": "high_vol" if rolling_vol and rolling_vol[-1] > np.median(rolling_vol) else "low_vol",
            "n_regime_changes": len(regime_changes),
        }

    @staticmethod
    def combined_analysis(returns: np.ndarray) -> dict:
        """Tail-risk score from the realised return series alone."""
        tail = BlackSwanDetector.analyze_tail_risk(returns)
        regime = BlackSwanDetector.detect_regime_change(returns)

        market_score = BlackSwanDetector._finite_float(tail["black_swan_score"])
        regime_score = min(100.0, BlackSwanDetector._finite_float(regime["n_regime_changes"] * 10))

        combined_score = BlackSwanDetector._finite_float(0.6 * market_score + 0.4 * regime_score)

        return {
            "combined_score": round(combined_score, 1),
            "alert_level": "CRITICAL" if combined_score > 75 else ("HIGH" if combined_score > 50 else ("MODERATE" if combined_score > 25 else "LOW")),
            "components": {
                "market_tail_risk": tail,
                "regime_analysis": regime,
            },
            "scores": {
                "market_score": round(market_score, 1),
                "regime_score": round(regime_score, 1),
            },
        }
