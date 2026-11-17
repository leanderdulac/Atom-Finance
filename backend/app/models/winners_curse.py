"""
Winner's curse / Deflated Sharpe Ratio.

Bailey & López de Prado (2014): the max of N independent zero-edge Sharpes
grows like σ_SR · √(2 ln N). Selecting the in-sample champion is a lottery
ticket, not a forecast. DSR asks how unusual that champion still looks after
paying for the search.
"""

from __future__ import annotations

from collections.abc import Sequence
from math import inf
from typing import Any

import numpy as np
from scipy.stats import kurtosis as sp_kurtosis
from scipy.stats import norm
from scipy.stats import skew as sp_skew

EULER_GAMMA = 0.5772156649015329
DEFAULT_PERIODS = 252.0
DEFAULT_DSR_THRESHOLD = 0.95

_WHAT_BROKE = [
    "Trials are modelled as independent; a grid search on overlapping windows is not.",
    "√(2 ln N) is the leading Gaussian EVT term — finite-N bias remains.",
    "DSR > 0.95 rejects luck under this model; it does not prove a tradable edge.",
    "Non-normality needs the skew/kurtosis terms; the simulator is iid Gaussian.",
    "This does not authorize live trading. eligible_for_live_trading stays false.",
]


def annualized_sharpe(returns: np.ndarray, periods_per_year: float = DEFAULT_PERIODS) -> float:
    r = np.asarray(returns, dtype=np.float64)
    r = r[np.isfinite(r)]
    if len(r) < 3:
        raise ValueError("Need ≥3 returns for Sharpe")
    s = float(np.std(r, ddof=1))
    if s < 1e-16:
        return 0.0
    return float(np.sqrt(periods_per_year) * np.mean(r) / s)


def sharpe_moments(returns, periods_per_year: float = DEFAULT_PERIODS) -> dict[str, float]:
    """Annualized Sharpe plus sample skew and excess kurtosis (γ₄−3)."""
    r = np.asarray(returns, dtype=np.float64)
    r = r[np.isfinite(r)]
    if len(r) < 3:
        raise ValueError("Need ≥3 returns for Sharpe")
    sr = annualized_sharpe(r, periods_per_year)
    skew = float(sp_skew(r, bias=False)) if len(r) >= 3 else 0.0
    ek = float(sp_kurtosis(r, fisher=True, bias=False)) if len(r) >= 4 else 0.0
    if not np.isfinite(skew):
        skew = 0.0
    if not np.isfinite(ek):
        ek = 0.0
    return {
        "n_obs": float(len(r)),
        "observed_sharpe": sr,
        "skew": skew,
        "excess_kurtosis": ek,
        "periods_per_year": float(periods_per_year),
    }


def sharpe_sampling_se(
    n_obs: int,
    sharpe_ann: float = 0.0,
    periods_per_year: float = DEFAULT_PERIODS,
) -> float:
    """SE of an annualized Sharpe under iid Gaussian returns (Lo 2002)."""
    if n_obs < 3:
        raise ValueError("Need ≥3 observations")
    sr_d = sharpe_ann / np.sqrt(periods_per_year)
    se_d = np.sqrt((1.0 + 0.5 * sr_d**2) / (n_obs - 1))
    return float(se_d * np.sqrt(periods_per_year))


def _z_blp(n_trials: float) -> float:
    """Bailey–López de Prado expected-max z (Gumbel interpolation of Φ⁻¹)."""
    if n_trials <= 1:
        raise ValueError("Need >1 trials for the expected-max z")
    return float(
        (1.0 - EULER_GAMMA) * norm.ppf(1.0 - 1.0 / n_trials)
        + EULER_GAMMA * norm.ppf(1.0 - 1.0 / (n_trials * np.e))
    )


def _se_hat(
    observed_sharpe: float,
    n_obs: int,
    skew: float = 0.0,
    excess_kurtosis: float = 0.0,
    periods_per_year: float = DEFAULT_PERIODS,
) -> float:
    """Lo (2002) + Bailey non-normal SE of an annualized Sharpe."""
    if n_obs < 3:
        raise ValueError("Need ≥3 observations")
    sr_d = observed_sharpe / np.sqrt(periods_per_year)
    inside = (
        1.0
        - skew * sr_d
        + ((excess_kurtosis + 3.0) - 1.0) / 4.0 * sr_d**2
    ) / (n_obs - 1)
    se_d = np.sqrt(max(float(inside), 0.0))
    return float(se_d * np.sqrt(periods_per_year))


def expected_max_sharpe(
    n_trials: int | float,
    n_obs: int,
    sharpe_ann: float = 0.0,
    periods_per_year: float = DEFAULT_PERIODS,
    trial_sharpes: Sequence[float] | None = None,
    se: float | None = None,
) -> dict[str, Any]:
    """Expected maximum of N independent estimated Sharpes (true mean = sharpe_ann).

    `se` or the empirical std of `trial_sharpes` (annualized) is used when
    given; otherwise the Lo SE around `sharpe_ann` (0 under H0).
    """
    if n_trials <= 1:
        raise ValueError("Need ≥2 trials")
    if trial_sharpes is not None:
        ts = np.asarray(trial_sharpes, dtype=np.float64)
        ts = ts[np.isfinite(ts)]
        if len(ts) < 2:
            raise ValueError("Need ≥2 finite trial Sharpes to estimate variance")
        se_used = float(np.std(ts, ddof=1))
    elif se is not None:
        se_used = float(se)
    else:
        se_used = sharpe_sampling_se(n_obs, sharpe_ann, periods_per_year)
    z_lead = float(np.sqrt(2.0 * np.log(n_trials)))
    z_blp = _z_blp(n_trials)
    return {
        "se": round(se_used, 6),
        "expected_max_sqrt_2lnN": round(se_used * z_lead, 6),
        "expected_max_blp": round(se_used * z_blp, 6),
        "z_sqrt_2lnN": round(z_lead, 6),
        "z_blp": round(z_blp, 6),
        "n_trials": n_trials,
        "n_obs": n_obs,
    }


def probabilistic_sharpe(
    observed_sharpe: float,
    n_obs: int,
    sr_benchmark: float = 0.0,
    skew: float = 0.0,
    excess_kurtosis: float = 0.0,
    periods_per_year: float = DEFAULT_PERIODS,
    threshold: float = DEFAULT_DSR_THRESHOLD,
) -> dict[str, Any]:
    """PSR[SR*] = Φ((SR̂ − SR*)/σ̂). Sharpe arguments are annualized."""
    if n_obs < 3:
        raise ValueError("Need ≥3 observations")
    se_hat = _se_hat(observed_sharpe, n_obs, skew, excess_kurtosis, periods_per_year)
    z = 0.0 if se_hat < 1e-16 else (observed_sharpe - sr_benchmark) / se_hat
    psr = float(norm.cdf(z))
    return {
        "observed_sharpe": round(float(observed_sharpe), 6),
        "sr_benchmark": round(float(sr_benchmark), 6),
        "psr": round(psr, 6),
        "z": round(float(z), 6),
        "se_hat": round(se_hat, 6),
        "n_obs": n_obs,
        "significant_at_95": bool(psr >= threshold),
    }


def deflated_sharpe(
    observed_sharpe: float,
    n_trials: int | float,
    n_obs: int,
    skew: float = 0.0,
    excess_kurtosis: float = 0.0,
    periods_per_year: float = DEFAULT_PERIODS,
    trial_sharpes: Sequence[float] | None = None,
) -> dict[str, Any]:
    """
    DSR = Φ((SR̂ − SR*) / σ̂) with SR* the expected max under N trials.

    excess_kurtosis is γ₄ − 3 (0 for Gaussian). When `trial_sharpes` is
    given, SR* uses the empirical std of those Sharpes (Bailey & López de
    Prado 2014); otherwise SR* uses the theoretical SE of this Sharpe.
    """
    if n_trials <= 1 or n_obs < 3:
        raise ValueError("Need >1 trials and ≥3 observations")
    se_hat = _se_hat(observed_sharpe, n_obs, skew, excess_kurtosis, periods_per_year)
    z_blp = _z_blp(n_trials)
    if trial_sharpes is not None:
        ts = np.asarray(trial_sharpes, dtype=np.float64)
        ts = ts[np.isfinite(ts)]
        if len(ts) < 2:
            raise ValueError("Need ≥2 finite trial Sharpes to estimate variance")
        sr_star = float(np.std(ts, ddof=1)) * z_blp
    else:
        sr_star = se_hat * z_blp
    z = 0.0 if se_hat < 1e-16 else (observed_sharpe - sr_star) / se_hat
    dsr = float(norm.cdf(z))
    return {
        "observed_sharpe": round(float(observed_sharpe), 6),
        "sr_star": round(float(sr_star), 6),
        "deflated_sharpe_prob": round(dsr, 6),
        "z": round(float(z), 6),
        "se_hat": round(se_hat, 6),
        "n_trials": n_trials,
        "n_obs": n_obs,
        "significant_at_95": bool(dsr >= 0.95),
        "haircut": round(float(observed_sharpe - sr_star), 6),
        "expected_max_blp": round(float(sr_star), 6),
        "z_blp": round(z_blp, 6),
    }


def min_track_record_length(
    observed_sharpe: float,
    sr_benchmark: float = 0.0,
    skew: float = 0.0,
    excess_kurtosis: float = 0.0,
    threshold: float = DEFAULT_DSR_THRESHOLD,
    periods_per_year: float = DEFAULT_PERIODS,
) -> float:
    """Minimum number of observations so that PSR[SR*] ≥ `threshold`.

    Returns +inf when the observed Sharpe does not exceed the benchmark
    (a longer sample cannot help if SR̂ stays at or below SR*).
    """
    if observed_sharpe <= sr_benchmark:
        return inf
    z_a = float(norm.ppf(threshold))
    sr_d = observed_sharpe / np.sqrt(periods_per_year)
    g = 1.0 - skew * sr_d + ((excess_kurtosis + 3.0) - 1.0) / 4.0 * sr_d**2
    g = max(float(g), 0.0)
    mtrl = 1.0 + g * periods_per_year * (z_a / (observed_sharpe - sr_benchmark)) ** 2
    return float(mtrl)


def simulate(
    n_strategies: int = 400,
    t_is: int = 504,
    t_oos: int = 252,
    daily_vol: float = 0.01,
    seed: int = 7,
) -> dict[str, Any]:
    """
    N iid Gaussian strategies, true E[r]=0. Pick the IS Sharpe champion.
    The OOS Sharpe of that champion is the lottery settlement.
    """
    if not 10 <= n_strategies <= 2000:
        raise ValueError("n_strategies must be in [10, 2000]")
    if not 60 <= t_is <= 2500 or not 60 <= t_oos <= 2500:
        raise ValueError("t_is and t_oos must be in [60, 2500]")
    if not 1e-4 <= daily_vol <= 0.1:
        raise ValueError("daily_vol out of range")

    rng = np.random.default_rng(seed)
    t = t_is + t_oos
    # (n_strategies, t) independent N(0, daily_vol²)
    panel = rng.normal(0.0, daily_vol, size=(n_strategies, t))
    is_sr = np.array([annualized_sharpe(panel[i, :t_is]) for i in range(n_strategies)])
    oos_sr = np.array([annualized_sharpe(panel[i, t_is:]) for i in range(n_strategies)])
    winner = int(np.argmax(is_sr))
    env = expected_max_sharpe(n_strategies, t_is, 0.0)
    dsr = deflated_sharpe(float(is_sr[winner]), n_strategies, t_is)

    # Pearson of the cloud — should be ~0 under H0
    if np.std(is_sr) < 1e-12 or np.std(oos_sr) < 1e-12:
        corr = 0.0
    else:
        corr = float(np.corrcoef(is_sr, oos_sr)[0, 1])

    cloud = [
        {"is": round(float(a), 4), "oos": round(float(b), 4), "winner": i == winner}
        for i, (a, b) in enumerate(zip(is_sr, oos_sr, strict=True))
    ]
    naive_replay = float(is_sr[winner])  # open circle: "if the backtest repeated"
    return {
        "n_strategies": n_strategies,
        "t_is": t_is,
        "t_oos": t_oos,
        "true_sharpe": 0.0,
        "winner_index": winner,
        "winner_is": round(float(is_sr[winner]), 4),
        "winner_oos": round(float(oos_sr[winner]), 4),
        "naive_replay_is": round(naive_replay, 4),
        "median_is": round(float(np.median(is_sr)), 4),
        "median_oos": round(float(np.median(oos_sr)), 4),
        "is_oos_corr": round(corr, 4),
        "expected_max": env,
        "dsr": dsr,
        "cloud": cloud,
        "eligible_for_live_trading": False,
        "math": (
            "True E[r]=0 for every trial. SR_ann = √252 · μ̂/σ̂. "
            "E[max SR | H0] ≈ σ_SR · √(2 ln N) with σ_SR ≈ √(252/(T−1)). "
            "DSR = Φ((SR̂ − SR*)/σ̂), SR* from Bailey–López de Prado. "
            f"This champion was the max of {n_strategies} draws."
        ),
        "what_broke": list(_WHAT_BROKE),
    }
