"""
Copula Models for Multivariate Dependency Analysis
====================================================
Cópulas isolam a estrutura de dependência das distribuições marginais,
permitindo modelar como ativos colapsam (ou explodem) juntos em crises.

Implemented:
- GaussianCopula   — dependência simétrica, sem cauda
- StudentTCopula   — caudas pesadas simétricas (crashes E booms juntos)
- ClaytonCopula    — dependência de cauda INFERIOR (crashes simultâneos)
- GumbelCopula     — dependência de cauda SUPERIOR (booms simultâneos)
- FrankCopula      — dependência simétrica, sem cauda (como Gaussian)
- fit_best_copula  — seleciona a melhor cópula por AIC
- empirical_copula — transforma dados em pseudo-observações uniformes
"""

import numpy as np
from dataclasses import dataclass
from functools import partial
from scipy import stats
from scipy.optimize import minimize_scalar, minimize
from scipy.special import gammaln
from typing import Optional


# ── Data class ────────────────────────────────────────────────────────────────

@dataclass
class CopulaFitResult:
    copula_type: str
    parameters: dict
    log_likelihood: float
    aic: float
    bic: float
    lower_tail_dependence: float    # λ_L  (crashes together)
    upper_tail_dependence: float    # λ_U  (booms together)
    interpretation: str


# ── Helpers ───────────────────────────────────────────────────────────────────

def empirical_copula(data: np.ndarray) -> np.ndarray:
    """
    Transform each column to pseudo-observations in (0,1) using probability
    integral transform (rank-based).  Avoids boundary issues via u = r/(n+1).
    """
    n, d = data.shape
    u = np.zeros_like(data, dtype=float)
    for j in range(d):
        u[:, j] = stats.rankdata(data[:, j]) / (n + 1.0)
    return u


def _clip(u: np.ndarray, eps: float = 1e-7) -> np.ndarray:
    return np.clip(u, eps, 1.0 - eps)


# ── Gaussian Copula ───────────────────────────────────────────────────────────

class GaussianCopula:
    """
    Gaussian (Normal) Copula.
    Symmetric, no tail dependence — λ_L = λ_U = 0.
    Suitable for normal market conditions.
    """

    def __init__(self):
        self.corr_matrix: np.ndarray | None = None

    def fit(self, u: np.ndarray) -> CopulaFitResult:
        u = _clip(u)
        n, d = u.shape
        z = stats.norm.ppf(u)
        self.corr_matrix = np.corrcoef(z.T)

        # Log-likelihood of the Gaussian copula
        log_det = float(np.linalg.slogdet(self.corr_matrix)[1])
        inv_corr = np.linalg.inv(self.corr_matrix)
        identity = np.eye(d)
        ll = 0.0
        for i in range(n):
            zi = z[i]
            ll += -0.5 * log_det - 0.5 * float(zi @ (inv_corr - identity) @ zi)

        n_params = d * (d - 1) / 2
        return CopulaFitResult(
            copula_type="gaussian",
            parameters={"correlation_matrix": self.corr_matrix.tolist()},
            log_likelihood=ll,
            aic=-2.0 * ll + 2.0 * n_params,
            bic=-2.0 * ll + n_params * np.log(n),
            lower_tail_dependence=0.0,
            upper_tail_dependence=0.0,
            interpretation="Dependência simétrica, sem clustering de cauda — condições normais de mercado.",
        )

    def simulate(self, n: int, corr_matrix: Optional[np.ndarray] = None) -> np.ndarray:
        R = corr_matrix if corr_matrix is not None else self.corr_matrix
        L = np.linalg.cholesky(R)
        d = R.shape[0]
        z = np.random.standard_normal((n, d))
        return _clip(stats.norm.cdf(z @ L.T))


# ── Student-t Copula ──────────────────────────────────────────────────────────

class StudentTCopula:
    """
    Student-t Copula.
    Symmetric fat-tailed dependence — λ_L = λ_U > 0.
    Assets crash AND boom together; degree of tail dependence controlled by ν (df).
    """

    def __init__(self):
        self.corr_matrix: np.ndarray | None = None
        self.df: float | None = None

    def _log_likelihood(self, u: np.ndarray, corr: np.ndarray, df: float) -> float:
        n, d = u.shape
        u_clip = _clip(u)
        t_obs = stats.t.ppf(u_clip, df=df)
        try:
            inv_corr = np.linalg.inv(corr)
            log_det = float(np.linalg.slogdet(corr)[1])
        except np.linalg.LinAlgError:
            return -1e12

        ll = 0.0
        log_const = (
            gammaln((df + d) / 2.0)
            - gammaln(df / 2.0)
            - (d / 2.0) * np.log(df * np.pi)
            - 0.5 * log_det
        )
        marg_const = d * (gammaln((df + 1) / 2.0) - gammaln(df / 2.0) - 0.5 * np.log(df * np.pi))
        for i in range(n):
            ti = t_obs[i]
            quad = float(ti @ inv_corr @ ti)
            joint = log_const - ((df + d) / 2.0) * np.log(1.0 + quad / df)
            marg = float(np.sum(stats.t.logpdf(ti, df=df)))
            ll += joint - marg
        return ll

    def fit(self, u: np.ndarray, df_grid: Optional[np.ndarray] = None) -> CopulaFitResult:
        u = _clip(u)
        n, d = u.shape
        if df_grid is None:
            df_grid = np.arange(2.0, 31.0, 1.0)

        # Bootstrap correlation from normal scores
        z = stats.norm.ppf(u)
        self.corr_matrix = np.corrcoef(z.T)

        best_ll, best_df = -np.inf, 5.0
        for df in df_grid:
            t_obs = stats.t.ppf(u, df=df)
            corr_candidate = np.corrcoef(t_obs.T)
            # ensure positive-definite
            eigvals = np.linalg.eigvalsh(corr_candidate)
            if np.any(eigvals <= 0):
                continue
            ll_candidate = self._log_likelihood(u, corr_candidate, df)
            if ll_candidate > best_ll:
                best_ll = ll_candidate
                best_df = df
                self.corr_matrix = corr_candidate

        self.df = best_df

        # Tail dependence (bivariate formula)
        if d == 2:
            rho = float(self.corr_matrix[0, 1])
            td = float(
                2.0
                * stats.t.cdf(
                    -np.sqrt((self.df + 1.0) * (1.0 - rho) / (1.0 + rho)),
                    df=self.df + 1.0,
                )
            )
        else:
            td = float(np.mean(
                [2.0 * stats.t.cdf(-np.sqrt((self.df + 1) * (1 - self.corr_matrix[i, j]) / (1 + self.corr_matrix[i, j])), df=self.df + 1)
                 for i in range(d) for j in range(d) if i < j]
            )) if d > 2 else 0.0

        n_params = d * (d - 1) / 2 + 1
        return CopulaFitResult(
            copula_type="student_t",
            parameters={"df": float(self.df), "correlation_matrix": self.corr_matrix.tolist()},
            log_likelihood=best_ll,
            aic=-2.0 * best_ll + 2.0 * n_params,
            bic=-2.0 * best_ll + n_params * np.log(n),
            lower_tail_dependence=td,
            upper_tail_dependence=td,
            interpretation=f"Caudas pesadas simétricas (ν≈{self.df:.0f}). Ativos crasham E explodem juntos — λ={td:.3f}.",
        )

    def simulate(self, n: int) -> np.ndarray:
        d = self.corr_matrix.shape[0]
        L = np.linalg.cholesky(self.corr_matrix)
        z = np.random.standard_normal((n, d))
        chi2 = np.random.chisquare(self.df, size=n)
        t_samples = z @ L.T / np.sqrt(chi2[:, None] / self.df)
        return _clip(stats.t.cdf(t_samples, df=self.df))


# ── Clayton Copula ────────────────────────────────────────────────────────────

class ClaytonCopula:
    """
    Clayton Copula — forte dependência de cauda INFERIOR.
    Ativos tendem a crashar simultaneamente.
    λ_L = 2^(-1/θ),  λ_U = 0.
    Suporta apenas dados bivariados (d=2).
    """

    def __init__(self):
        self.theta: float | None = None

    def fit(self, u: np.ndarray) -> CopulaFitResult:
        if u.shape[1] != 2:
            raise ValueError("ClaytonCopula suporta apenas dados bivariados (2 ativos).")
        u = _clip(u)
        n = len(u)
        u1, u2 = u[:, 0], u[:, 1]

        def neg_ll(theta: float) -> float:
            if theta <= 1e-6:
                return 1e12
            try:
                log_c = (
                    np.log(1.0 + theta)
                    + (-1.0 - 1.0 / theta) * np.log(u1 ** (-theta) + u2 ** (-theta) - 1.0)
                    + (-theta - 1.0) * (np.log(u1) + np.log(u2))
                )
                return -float(np.sum(log_c))
            except Exception:
                return 1e12

        res = minimize_scalar(neg_ll, bounds=(1e-6, 30.0), method="bounded")
        self.theta = float(res.x)
        ll = float(-res.fun)
        tail_l = float(2.0 ** (-1.0 / self.theta))

        return CopulaFitResult(
            copula_type="clayton",
            parameters={"theta": self.theta},
            log_likelihood=ll,
            aic=-2.0 * ll + 2.0,
            bic=-2.0 * ll + np.log(n),
            lower_tail_dependence=tail_l,
            upper_tail_dependence=0.0,
            interpretation=f"Dependência de cauda inferior forte (θ={self.theta:.2f}). Ativos crasham juntos — λ_L={tail_l:.3f}.",
        )

    def simulate(self, n: int) -> np.ndarray:
        u = np.random.uniform(0, 1, n)
        t = np.random.uniform(0, 1, n)
        # Conditional quantile of Clayton
        v = u * (t ** (-self.theta / (1.0 + self.theta)) - 1.0 + u ** self.theta) ** (-1.0 / self.theta)
        return _clip(np.column_stack([u, v]))


# ── Gumbel Copula ─────────────────────────────────────────────────────────────

class GumbelCopula:
    """
    Gumbel Copula — forte dependência de cauda SUPERIOR.
    Ativos tendem a explodir (boom) simultaneamente.
    λ_U = 2 - 2^(1/θ),  λ_L = 0.
    Suporta apenas dados bivariados (d=2).
    """

    def __init__(self):
        self.theta: float | None = None

    def fit(self, u: np.ndarray) -> CopulaFitResult:
        if u.shape[1] != 2:
            raise ValueError("GumbelCopula suporta apenas dados bivariados (2 ativos).")
        u = _clip(u)
        n = len(u)
        u1, u2 = u[:, 0], u[:, 1]

        def neg_ll(theta: float) -> float:
            if theta < 1.0:
                return 1e12
            try:
                lu1, lu2 = -np.log(u1), -np.log(u2)
                A = (lu1 ** theta + lu2 ** theta) ** (1.0 / theta)
                log_c = (
                    -A
                    + (theta - 1.0) * (np.log(lu1) + np.log(lu2))
                    - np.log(u1) - np.log(u2)
                    + np.log(
                        A ** (2.0 - 2.0 / theta)
                        + (theta - 1.0) * A ** (1.0 - 2.0 / theta)
                    )
                    - (2.0 - 1.0 / theta) * np.log(lu1 ** theta + lu2 ** theta)
                )
                return -float(np.sum(log_c))
            except Exception:
                return 1e12

        res = minimize_scalar(neg_ll, bounds=(1.0, 30.0), method="bounded")
        self.theta = float(max(1.0, res.x))
        ll = float(-res.fun)
        tail_u = float(2.0 - 2.0 ** (1.0 / self.theta))

        return CopulaFitResult(
            copula_type="gumbel",
            parameters={"theta": self.theta},
            log_likelihood=ll,
            aic=-2.0 * ll + 2.0,
            bic=-2.0 * ll + np.log(n),
            lower_tail_dependence=0.0,
            upper_tail_dependence=tail_u,
            interpretation=f"Dependência de cauda superior forte (θ={self.theta:.2f}). Ativos explodem juntos — λ_U={tail_u:.3f}.",
        )

    def simulate(self, n: int) -> np.ndarray:
        """Marshall-Olkin frailty simulation."""
        alpha = 1.0 / self.theta
        # Stable frailty via Chambers-Mallows-Stuck method (α-stable, β=1)
        uniform_samples = np.random.uniform(0, np.pi, n)
        exp_samples = np.random.exponential(1.0, n)
        S = (
            np.sin(alpha * uniform_samples) / (np.sin(uniform_samples) ** (1.0 / alpha))
            * (np.sin((1.0 - alpha) * uniform_samples) / exp_samples) ** ((1.0 - alpha) / alpha)
        )
        e1 = np.random.exponential(1.0, n)
        e2 = np.random.exponential(1.0, n)
        u1 = np.exp(-((e1 / S) ** alpha))
        u2 = np.exp(-((e2 / S) ** alpha))
        return _clip(np.column_stack([u1, u2]))


# ── Frank Copula ──────────────────────────────────────────────────────────────

class FrankCopula:
    """
    Frank Copula — dependência simétrica, SEM dependência de cauda.
    λ_L = λ_U = 0.  Adequado para mercados com correlação moderada.
    Suporta apenas dados bivariados (d=2).
    """

    def __init__(self):
        self.theta: float | None = None

    def fit(self, u: np.ndarray) -> CopulaFitResult:
        if u.shape[1] != 2:
            raise ValueError("FrankCopula suporta apenas dados bivariados (2 ativos).")
        u = _clip(u)
        n = len(u)
        u1, u2 = u[:, 0], u[:, 1]

        def neg_ll(theta: float) -> float:
            if abs(theta) < 1e-6:
                return 1e12
            try:
                e_t = np.exp(-theta)
                e1 = np.exp(-theta * u1)
                e2 = np.exp(-theta * u2)
                num = theta * (1.0 - e_t) * np.exp(-theta * (u1 + u2))
                denom = ((1.0 - e_t) - (1.0 - e1) * (1.0 - e2)) ** 2
                if np.any(denom <= 0) or np.any(num <= 0):
                    return 1e12
                return -float(np.sum(np.log(num / denom)))
            except Exception:
                return 1e12

        res = minimize_scalar(neg_ll, bounds=(-30.0, 30.0), method="bounded")
        self.theta = float(res.x)
        ll = float(-res.fun)

        return CopulaFitResult(
            copula_type="frank",
            parameters={"theta": self.theta},
            log_likelihood=ll,
            aic=-2.0 * ll + 2.0,
            bic=-2.0 * ll + np.log(n),
            lower_tail_dependence=0.0,
            upper_tail_dependence=0.0,
            interpretation=f"Dependência simétrica sem clustering de cauda (θ={self.theta:.2f}). Similar à Gaussiana.",
        )

    def simulate(self, n: int) -> np.ndarray:
        u = np.random.uniform(0.0, 1.0, n)
        t = np.random.uniform(0.0, 1.0, n)
        theta = self.theta
        e_t = np.exp(-theta)
        # Conditional quantile (inverse of Frank conditional CDF)
        denom = t * (np.exp(-theta * u) - 1.0) - np.exp(-theta * u)
        with np.errstate(divide="ignore", invalid="ignore"):
            v = -np.log(1.0 + t * (e_t - 1.0) / denom) / theta
        return _clip(np.column_stack([u, v]))


# ── Model selection ───────────────────────────────────────────────────────────

def fit_best_copula(u: np.ndarray) -> dict:
    """
    Fit multiple copulas and rank by AIC.

    For d > 2 only Gaussian and Student-t are available (multivariate extensions).
    For d = 2 all five copulas are tried.
    """
    d = u.shape[1]
    results: dict[str, dict] = {}

    candidates: dict[str, object]
    if d == 2:
        candidates = {
            "gaussian": GaussianCopula(),
            "student_t": StudentTCopula(),
            "clayton": ClaytonCopula(),
            "gumbel": GumbelCopula(),
            "frank": FrankCopula(),
        }
    else:
        candidates = {
            "gaussian": GaussianCopula(),
            "student_t": StudentTCopula(),
        }

    for name, copula in candidates.items():
        try:
            fit: CopulaFitResult = copula.fit(u)
            results[name] = {
                "parameters": fit.parameters,
                "log_likelihood": round(fit.log_likelihood, 4),
                "aic": round(fit.aic, 4),
                "bic": round(fit.bic, 4),
                "lower_tail_dependence": round(fit.lower_tail_dependence, 4),
                "upper_tail_dependence": round(fit.upper_tail_dependence, 4),
                "interpretation": fit.interpretation,
            }
        except Exception as exc:
            results[name] = {"error": str(exc)}

    valid = {k: v for k, v in results.items() if "aic" in v}
    if valid:
        results["best_copula"] = min(valid, key=lambda k: valid[k]["aic"])

    return results
