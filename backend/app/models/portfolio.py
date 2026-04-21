"""
Portfolio Optimization
- Markowitz Mean-Variance
- Risk Parity
- Black-Litterman
- Minimum Variance
- Maximum Sharpe Ratio
"""
import numpy as np
from scipy.optimize import minimize
from typing import Optional


class PortfolioOptimizer:
    """Portfolio optimization suite."""

    def __init__(self, returns: np.ndarray, asset_names: Optional[list[str]] = None):
        self.returns = np.asarray(returns, dtype=np.float64)
        self.n_assets = self.returns.shape[1] if self.returns.ndim > 1 else 1
        self.asset_names = asset_names or [f"Asset_{i+1}" for i in range(self.n_assets)]
        self.mean_returns = np.mean(self.returns, axis=0) * 252
        self.cov_matrix = np.cov(self.returns.T) * 252

    def _portfolio_performance(self, weights: np.ndarray) -> tuple[float, float]:
        ret = np.dot(weights, self.mean_returns)
        vol = np.sqrt(np.dot(weights.T, np.dot(self.cov_matrix, weights)))
        return float(ret), float(vol)

    def markowitz_efficient_frontier(self, n_points: int = 50,
                                     risk_free_rate: float = 0.02,
                                     allow_short: bool = False) -> dict:
        """Generate the efficient frontier and optimal portfolios."""
        bounds = [(-1.0 if allow_short else 0.0, 1.0)] * self.n_assets
        constraints = [{"type": "eq", "fun": lambda w: np.sum(w) - 1}]

        # Find min and max return feasible
        min_ret = float(np.min(self.mean_returns))
        max_ret = float(np.max(self.mean_returns))
        target_returns = np.linspace(min_ret, max_ret, n_points)

        frontier_returns = []
        frontier_volatilities = []
        frontier_weights = []

        for target in target_returns:
            cons = constraints + [{"type": "eq", "fun": lambda w, t=target: np.dot(w, self.mean_returns) - t}]
            w0 = np.ones(self.n_assets) / self.n_assets

            try:
                result = minimize(
                    lambda w: np.sqrt(np.dot(w.T, np.dot(self.cov_matrix, w))),
                    w0, method="SLSQP", bounds=bounds, constraints=cons,
                )
                if result.success:
                    ret, vol = self._portfolio_performance(result.x)
                    frontier_returns.append(round(ret * 100, 4))
                    frontier_volatilities.append(round(vol * 100, 4))
                    frontier_weights.append([round(w, 4) for w in result.x])
            except Exception:
                continue

        # Maximum Sharpe Ratio portfolio
        max_sharpe = self.max_sharpe_ratio(risk_free_rate, allow_short)
        # Minimum Variance portfolio
        min_var = self.min_variance(allow_short)

        return {
            "frontier": {
                "returns": frontier_returns,
                "volatilities": frontier_volatilities,
                "weights": frontier_weights,
            },
            "max_sharpe_portfolio": max_sharpe,
            "min_variance_portfolio": min_var,
            "asset_names": self.asset_names,
            "individual_assets": {
                "returns": [round(r * 100, 4) for r in self.mean_returns],
                "volatilities": [round(np.sqrt(self.cov_matrix[i, i]) * 100, 4) for i in range(self.n_assets)],
            },
            "correlation_matrix": np.corrcoef(self.returns.T).tolist(),
        }

    def max_sharpe_ratio(self, risk_free_rate: float = 0.02, allow_short: bool = False) -> dict:
        bounds = [(-1.0 if allow_short else 0.0, 1.0)] * self.n_assets
        constraints = [{"type": "eq", "fun": lambda w: np.sum(w) - 1}]

        def neg_sharpe(weights):
            ret, vol = self._portfolio_performance(weights)
            return -(ret - risk_free_rate) / vol

        w0 = np.ones(self.n_assets) / self.n_assets
        result = minimize(neg_sharpe, w0, method="SLSQP", bounds=bounds, constraints=constraints)

        ret, vol = self._portfolio_performance(result.x)
        sharpe = (ret - risk_free_rate) / vol

        return {
            "weights": {name: round(w, 4) for name, w in zip(self.asset_names, result.x)},
            "expected_return": round(ret * 100, 4),
            "volatility": round(vol * 100, 4),
            "sharpe_ratio": round(sharpe, 4),
        }

    def min_variance(self, allow_short: bool = False) -> dict:
        bounds = [(-1.0 if allow_short else 0.0, 1.0)] * self.n_assets
        constraints = [{"type": "eq", "fun": lambda w: np.sum(w) - 1}]

        def portfolio_vol(weights):
            return np.sqrt(np.dot(weights.T, np.dot(self.cov_matrix, weights)))

        w0 = np.ones(self.n_assets) / self.n_assets
        result = minimize(portfolio_vol, w0, method="SLSQP", bounds=bounds, constraints=constraints)

        ret, vol = self._portfolio_performance(result.x)

        return {
            "weights": {name: round(w, 4) for name, w in zip(self.asset_names, result.x)},
            "expected_return": round(ret * 100, 4),
            "volatility": round(vol * 100, 4),
        }

    def risk_parity(self) -> dict:
        """Equal risk contribution portfolio."""
        def risk_contribution(weights):
            port_vol = np.sqrt(np.dot(weights.T, np.dot(self.cov_matrix, weights)))
            marginal = np.dot(self.cov_matrix, weights) / port_vol
            rc = weights * marginal
            target = port_vol / self.n_assets
            return np.sum((rc - target)**2)

        bounds = [(0.01, 1.0)] * self.n_assets
        constraints = [{"type": "eq", "fun": lambda w: np.sum(w) - 1}]
        w0 = np.ones(self.n_assets) / self.n_assets

        result = minimize(risk_contribution, w0, method="SLSQP", bounds=bounds, constraints=constraints)
        ret, vol = self._portfolio_performance(result.x)

        # Calculate risk contributions
        port_vol = np.sqrt(np.dot(result.x.T, np.dot(self.cov_matrix, result.x)))
        marginal = np.dot(self.cov_matrix, result.x) / port_vol
        rc = result.x * marginal

        return {
            "weights": {name: round(w, 4) for name, w in zip(self.asset_names, result.x)},
            "risk_contributions": {name: round(float(r), 4) for name, r in zip(self.asset_names, rc)},
            "expected_return": round(ret * 100, 4),
            "volatility": round(vol * 100, 4),
        }

    def black_litterman(self, views: dict, tau: float = 0.05,
                        risk_free_rate: float = 0.02) -> dict:
        """
        Black-Litterman model.
        views: {"Asset_1": 0.10, "Asset_2": 0.05} - absolute return views
        """
        # Market cap weights (assume equal for simplicity)
        w_mkt = np.ones(self.n_assets) / self.n_assets

        # Implied equilibrium returns
        delta = (np.dot(w_mkt, self.mean_returns) - risk_free_rate) / np.dot(w_mkt, np.dot(self.cov_matrix, w_mkt))
        pi = delta * np.dot(self.cov_matrix, w_mkt)

        # Build view matrices
        n_views = len(views)
        P = np.zeros((n_views, self.n_assets))
        Q = np.zeros(n_views)

        for i, (asset, view_return) in enumerate(views.items()):
            if asset in self.asset_names:
                idx = self.asset_names.index(asset)
                P[i, idx] = 1
                Q[i] = view_return

        # Omega (uncertainty in views)
        Omega = np.diag(np.diag(tau * P @ self.cov_matrix @ P.T))

        # BL combined returns
        Sigma_tau = tau * self.cov_matrix
        M1 = np.linalg.inv(np.linalg.inv(Sigma_tau) + P.T @ np.linalg.inv(Omega) @ P)
        bl_returns = M1 @ (np.linalg.inv(Sigma_tau) @ pi + P.T @ np.linalg.inv(Omega) @ Q)

        # Optimal weights
        bl_weights = np.linalg.inv(delta * self.cov_matrix) @ bl_returns
        bl_weights = bl_weights / np.sum(bl_weights)  # Normalize

        return {
            "weights": {name: round(float(w), 4) for name, w in zip(self.asset_names, bl_weights)},
            "bl_expected_returns": {name: round(float(r) * 100, 4) for name, r in zip(self.asset_names, bl_returns)},
            "equilibrium_returns": {name: round(float(r) * 100, 4) for name, r in zip(self.asset_names, pi)},
        }
