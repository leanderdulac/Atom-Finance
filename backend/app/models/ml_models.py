"""
Naive forecast toys used only as labelled baselines.
Real research lives in research_validation.py (Ridge / RF + purged walk-forward).
"""

import numpy as np


class ExponentialSmoothingForecast:
    """Naive exponential-smoothing price path. Not a neural network."""

    def __init__(self, lookback: int = 60, hidden_size: int = 50):
        self.lookback = lookback
        self.hidden_size = hidden_size

    def predict(self, prices: np.ndarray, forecast_days: int = 30, seed: int | None = 42) -> dict:
        """Holt-style smoother + Gaussian residual — a baseline, not a learned LSTM."""
        if seed is not None:
            np.random.seed(seed)

        prices = np.asarray(prices, dtype=np.float64)
        returns = np.diff(np.log(prices))

        # Exponential smoothing + mean reversion. Intentionally not an LSTM.
        mu = np.mean(returns)
        sigma = np.std(returns)
        last_price = prices[-1]

        # Generate predictions with confidence intervals
        predictions = [last_price]
        upper_band = [last_price]
        lower_band = [last_price]

        for i in range(1, forecast_days + 1):
            # Mean-reverting random walk with momentum
            momentum = np.mean(returns[-min(10, len(returns)):])
            drift = 0.7 * mu + 0.3 * momentum
            pred_return = drift + 0.1 * sigma * np.random.randn()
            pred_price = predictions[-1] * np.exp(pred_return)
            predictions.append(round(float(pred_price), 2))

            # Confidence bands widen over time
            ci = 1.96 * sigma * np.sqrt(i) * predictions[-1]
            upper_band.append(round(float(pred_price + ci), 2))
            lower_band.append(round(float(pred_price - ci), 2))

        return {
            "model": "exponential_smoothing_baseline",
            "disclaimer": "Not a neural network. Naive smoother used as a forecast baseline.",
            "lookback": self.lookback,
            "forecast_days": forecast_days,
            "predictions": predictions[1:],
            "upper_band": upper_band[1:],
            "lower_band": lower_band[1:],
            "last_actual_price": round(float(last_price), 2),
            "predicted_return": round(float((predictions[-1] / last_price - 1) * 100), 2),
        }


