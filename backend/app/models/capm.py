"""CAPM, Beta, Kelly Criterion and GBM path simulation."""
from __future__ import annotations
import numpy as np
from scipy import stats


class CAPMAnalyzer:
    @staticmethod
    def compute_beta(asset_returns: np.ndarray, market_returns: np.ndarray) -> dict:
        """Compute Beta, Alpha, R² and CAPM expected return."""
        n = min(len(asset_returns), len(market_returns))
        r_a = np.asarray(asset_returns[-n:], dtype=np.float64)
        r_m = np.asarray(market_returns[-n:], dtype=np.float64)
        slope, intercept, r_value, p_value, std_err = stats.linregress(r_m, r_a)
        return {
            "beta": round(float(slope), 4),
            "alpha_daily": round(float(intercept), 6),
            "alpha_annual": round(float(intercept * 252), 4),
            "r_squared": round(float(r_value ** 2), 4),
            "p_value": round(float(p_value), 4),
            "std_err": round(float(std_err), 6),
            "n_observations": n,
        }

    @staticmethod
    def expected_return(beta: float, risk_free: float = 0.05, market_premium: float = 0.06) -> dict:
        """CAPM: E[R] = rf + β × (E[Rm] - rf)."""
        er = risk_free + beta * market_premium
        return {
            "expected_return_annual": round(er, 4),
            "risk_free_rate": risk_free,
            "market_premium": market_premium,
            "beta": beta,
            "formula": f"E[R] = {risk_free:.2%} + {beta:.4f} × {market_premium:.2%} = {er:.2%}",
        }

    @staticmethod
    def kelly_criterion(win_rate: float, payout_ratio: float, fraction: float = 1.0) -> dict:
        """
        Kelly Criterion: f* = (b·p - q) / b
        b = payout ratio (e.g. 2.0 means win 2x)
        p = probability of winning
        q = 1 - p
        fraction = fractional Kelly (e.g. 0.5 = half-Kelly)
        """
        p = win_rate
        q = 1.0 - p
        b = payout_ratio
        kelly_full = (b * p - q) / b
        kelly_frac = kelly_full * fraction
        edge = b * p - q  # expected value per unit bet
        return {
            "kelly_full": round(kelly_full, 4),
            "kelly_fraction": round(max(kelly_frac, 0.0), 4),
            "edge": round(edge, 4),
            "win_rate": p,
            "payout_ratio": b,
            "fraction_used": fraction,
            "recommended_position_pct": round(max(kelly_frac * 100, 0.0), 2),
            "interpretation": (
                "No edge — do not bet" if edge <= 0
                else f"Bet {max(kelly_frac * 100, 0):.1f}% of capital per trade"
            ),
        }

    @staticmethod
    def gbm_paths(
        S0: float,
        mu: float,
        sigma: float,
        T: float,
        n_steps: int,
        n_paths: int,
        seed: int | None = 42,
    ) -> dict:
        """
        Simulate GBM: dS = μ S dt + σ S dW
        Returns time array + matrix of paths.
        """
        if seed is not None:
            np.random.seed(seed)
        dt = T / n_steps
        times = np.linspace(0, T, n_steps + 1).tolist()
        Z = np.random.standard_normal((n_paths, n_steps))
        increments = (mu - 0.5 * sigma ** 2) * dt + sigma * np.sqrt(dt) * Z
        log_paths = np.concatenate(
            [np.zeros((n_paths, 1)), np.cumsum(increments, axis=1)], axis=1
        )
        paths = S0 * np.exp(log_paths)  # shape: (n_paths, n_steps+1)

        terminal = paths[:, -1]
        mean_path = paths.mean(axis=0)
        p5 = np.percentile(paths, 5, axis=0)
        p95 = np.percentile(paths, 95, axis=0)

        return {
            "S0": S0,
            "mu": mu,
            "sigma": sigma,
            "T": T,
            "n_steps": n_steps,
            "n_paths": n_paths,
            "time": [round(t, 4) for t in times],
            "paths": [[round(float(v), 4) for v in path] for path in paths[:min(50, n_paths)]],
            "mean": [round(float(v), 4) for v in mean_path],
            "p5": [round(float(v), 4) for v in p5],
            "p95": [round(float(v), 4) for v in p95],
            "terminal": {
                "mean": round(float(terminal.mean()), 4),
                "std": round(float(terminal.std()), 4),
                "p5": round(float(np.percentile(terminal, 5)), 4),
                "p50": round(float(np.median(terminal)), 4),
                "p95": round(float(np.percentile(terminal, 95)), 4),
                "prob_above_S0": round(float((terminal > S0).mean()), 4),
            },
        }

    @staticmethod
    def gbm_multi_paths(
        assets: list[dict],
        T: float,
        n_steps: int,
        n_paths: int,
        corr_matrix: list[list[float]] | None = None,
        seed: int | None = 42,
    ) -> dict:
        """
        Correlated multi-asset GBM via Cholesky decomposition.

        assets: list of dicts with keys  ticker, S0, mu, sigma
        corr_matrix: d×d correlation matrix (defaults to identity = independent)
        """
        if seed is not None:
            np.random.seed(seed)

        d = len(assets)
        dt = T / n_steps

        # Correlation / Cholesky
        if corr_matrix is not None:
            C = np.array(corr_matrix, dtype=float)
        else:
            C = np.eye(d)
        L = np.linalg.cholesky(C)          # lower triangular Cholesky factor

        times = np.linspace(0, T, n_steps + 1)

        # Simulate correlated increments: Z ~ N(0,I), W = L @ Z correlated
        Z = np.random.standard_normal((n_paths, n_steps, d))  # (paths, steps, assets)
        W = Z @ L.T                                            # correlated noise

        results = []
        for i, asset in enumerate(assets):
            S0 = float(asset["S0"])
            mu = float(asset["mu"])
            sigma = float(asset["sigma"])

            increments = (mu - 0.5 * sigma ** 2) * dt + sigma * np.sqrt(dt) * W[:, :, i]
            log_paths = np.concatenate(
                [np.zeros((n_paths, 1)), np.cumsum(increments, axis=1)], axis=1
            )
            paths = S0 * np.exp(log_paths)      # (n_paths, n_steps+1)

            mean_path = paths.mean(axis=0)
            p5 = np.percentile(paths, 5, axis=0)
            p95 = np.percentile(paths, 95, axis=0)
            terminal = paths[:, -1]

            # Normalised % return from S0 (for multi-asset overlay chart)
            mean_pct = (mean_path / S0 - 1.0) * 100

            results.append({
                "ticker": asset.get("ticker", f"asset_{i}"),
                "S0": S0,
                "mu": mu,
                "sigma": sigma,
                "mean": [round(float(v), 4) for v in mean_path],
                "p5": [round(float(v), 4) for v in p5],
                "p95": [round(float(v), 4) for v in p95],
                "mean_pct": [round(float(v), 3) for v in mean_pct],
                "terminal": {
                    "mean": round(float(terminal.mean()), 4),
                    "std": round(float(terminal.std()), 4),
                    "p5": round(float(np.percentile(terminal, 5)), 4),
                    "p50": round(float(np.median(terminal)), 4),
                    "p95": round(float(np.percentile(terminal, 95)), 4),
                    "prob_above_S0": round(float((terminal > S0).mean()), 4),
                    "expected_return_pct": round(float((terminal.mean() / S0 - 1.0) * 100), 2),
                },
            })

        return {
            "T": T,
            "n_steps": n_steps,
            "n_paths": n_paths,
            "time_days": [int(round(t * 252)) for t in times],
            "assets": results,
            "correlation_matrix": C.tolist(),
        }
