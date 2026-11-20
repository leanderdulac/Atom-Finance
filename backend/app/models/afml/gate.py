"""Promotion gate: DSR ≥ 0.95 and costs already in the returns.

Formulas are the ones in ``app.models.winners_curse`` (Bailey & López de Prado
2012/2014, Lo SE, Gumbel expected-max z). This module only decides whether a
candidate may be *considered* for paper simulation. It never authorizes live
trading.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from typing import Any

import numpy as np

from app.models.rejected_net_net import FAMILY_ID as REJECTED_NET_NET_FAMILY
from app.models.winners_curse import (
    DEFAULT_DSR_THRESHOLD,
    DEFAULT_PERIODS,
    EULER_GAMMA,
    annualized_sharpe,
    deflated_sharpe,
    expected_max_sharpe,
    min_track_record_length,
    probabilistic_sharpe,
    sharpe_moments,
    sharpe_sampling_se,
)

__all__ = [
    "DEFAULT_DSR_THRESHOLD",
    "DEFAULT_PERIODS",
    "EULER_GAMMA",
    "GateResult",
    "annualized_sharpe",
    "deflated_sharpe",
    "expected_max_sharpe",
    "gate",
    "gate_trial",
    "min_track_record_length",
    "probabilistic_sharpe",
    "sharpe_moments",
    "sharpe_sampling_se",
]

@dataclass
class GateResult:
    approved: bool
    reasons: list[str]
    observed_sharpe: float | None = None
    psr: float | None = None
    dsr: float | None = None
    sr_star: float | None = None
    min_trl: float | None = None
    n_obs: int | None = None
    n_trials: float | None = None
    n_eff: float | None = None
    se_hat: float | None = None
    skew: float | None = None
    excess_kurtosis: float | None = None
    costs_included: bool = False
    threshold: float = DEFAULT_DSR_THRESHOLD
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def gate(
    *,
    costs_included: bool,
    returns: Sequence[float] | None = None,
    observed_sharpe: float | None = None,
    n_obs: int | None = None,
    n_trials: float | None = None,
    skew: float = 0.0,
    excess_kurtosis: float = 0.0,
    trial_sharpes: Sequence[float] | None = None,
    n_eff: float | None = None,
    threshold: float = DEFAULT_DSR_THRESHOLD,
    periods_per_year: float = DEFAULT_PERIODS,
    sr_benchmark: float = 0.0,
) -> GateResult:
    """Approve or reject a candidate before promoting it to paper trading.

    Requires ``costs_included=True`` (returns already net of fees and spread).
    Default rule: DSR ≥ 0.95. Approval is only a research-to-paper gate,
    never authorization for live trading.
    """
    reasons: list[str] = []
    if returns is not None:
        moments = sharpe_moments(returns, periods_per_year)
        observed_sharpe = moments["observed_sharpe"]
        n_obs = int(moments["n_obs"])
        skew = moments["skew"]
        excess_kurtosis = moments["excess_kurtosis"]

    if not costs_included:
        reasons.append(
            "Retornos não foram declarados líquidos de taxa e spread; o gate recusa a promoção."
        )

    if observed_sharpe is None or n_obs is None:
        reasons.append("Sharpe observado e número de observações são obrigatórios (ou passe a série de retornos).")
        return GateResult(approved=False, reasons=reasons, costs_included=bool(costs_included), threshold=threshold)

    n_obs = int(n_obs)
    if n_obs < 3:
        reasons.append(f"Amostra curta demais (T={n_obs}; mínimo 3).")
        return GateResult(
            approved=False,
            reasons=reasons,
            observed_sharpe=float(observed_sharpe),
            n_obs=n_obs,
            costs_included=bool(costs_included),
            threshold=threshold,
        )

    n_used = n_eff if n_eff is not None else n_trials
    if n_used is None and trial_sharpes is not None:
        n_used = float(len(np.asarray(trial_sharpes, dtype=np.float64)))

    psr_out = probabilistic_sharpe(
        float(observed_sharpe), n_obs, sr_benchmark, skew, excess_kurtosis, periods_per_year, threshold
    )

    dsr_out = None
    sr_star = None
    dsr = None
    mtrl = None
    if n_used is None:
        reasons.append("Número de tentativas (N) não informado; o Sharpe deflacionado não pode ser calculado.")
    elif n_used < 2:
        reasons.append(
            "Só há uma tentativa independente (N ou N_eff < 2), então o Sharpe não foi "
            "deflacionado pela busca. Registre todas as variantes testadas."
        )
        sr_star = float(sr_benchmark)
        dsr = psr_out["psr"]
        mtrl = min_track_record_length(
            float(observed_sharpe), sr_star, skew, excess_kurtosis, threshold, periods_per_year
        )
        if dsr < threshold:
            reasons.append(
                f"PSR={dsr:.4f} está abaixo do limiar {threshold:.2f} (sem deflação por múltiplos testes)."
            )
    else:
        dsr_out = deflated_sharpe(
            float(observed_sharpe),
            float(n_used),
            n_obs,
            skew=skew,
            excess_kurtosis=excess_kurtosis,
            periods_per_year=periods_per_year,
            trial_sharpes=trial_sharpes,
        )
        sr_star = dsr_out["sr_star"]
        dsr = dsr_out["deflated_sharpe_prob"]
        mtrl = min_track_record_length(
            float(observed_sharpe), sr_star, skew, excess_kurtosis, threshold, periods_per_year
        )
        if dsr < threshold:
            reasons.append(
                f"DSR={dsr:.4f} está abaixo do limiar {threshold:.2f} "
                f"(SR̂={observed_sharpe:.3f}, SR*={sr_star:.3f}, N={n_used:g})."
            )
        if np.isfinite(mtrl) and n_obs < mtrl:
            reasons.append(
                f"A trilha (T={n_obs}) é mais curta que o comprimento mínimo de histórico "
                f"(MinTRL={mtrl:.0f}) para PSR[SR*] ≥ {threshold:.2f}."
            )
        elif not np.isfinite(mtrl):
            reasons.append(
                f"SR̂={observed_sharpe:.3f} não supera o Sharpe esperado da busca "
                f"(SR*={sr_star:.3f}); alongar a mesma amostra não resolve."
            )

    fail = (not costs_included) or dsr is None or dsr < threshold
    if fail:
        approved = False
    else:
        blocking = [r for r in reasons if not r.startswith("Só há uma tentativa")]
        approved = len(blocking) == 0

    return GateResult(
        approved=approved,
        reasons=reasons,
        observed_sharpe=round(float(observed_sharpe), 6),
        psr=psr_out["psr"],
        dsr=None if dsr is None else round(float(dsr), 6),
        sr_star=None if sr_star is None else round(float(sr_star), 6),
        min_trl=None if mtrl is None else (mtrl if not np.isfinite(mtrl) else round(float(mtrl), 4)),
        n_obs=n_obs,
        n_trials=None if n_trials is None else float(n_trials),
        n_eff=None if n_eff is None else float(n_eff),
        se_hat=psr_out["se_hat"],
        skew=round(float(skew), 6),
        excess_kurtosis=round(float(excess_kurtosis), 6),
        costs_included=bool(costs_included),
        threshold=threshold,
        details={"psr": psr_out, "dsr": dsr_out},
    )


def gate_trial(
    registry,
    family_id: str,
    *,
    costs_included: bool,
    trial_id: int | None = None,
    use_effective_n: bool = True,
    threshold: float = DEFAULT_DSR_THRESHOLD,
    cluster_corr: float = 0.5,
) -> GateResult:
    """Evaluate one registered trial against the family's history plus rejected searches.

    N is the family's own rows plus the recorded rejected net-net trials when
    this family is not that block. N_eff, when used, is still estimated from
    this family's return series only.
    """
    rows = registry.trials(family_id)
    if not rows:
        return GateResult(
            approved=False,
            reasons=[f"Nenhuma tentativa registrada na família '{family_id}'."],
            costs_included=bool(costs_included),
            threshold=threshold,
        )
    if trial_id is None:
        trial = rows[-1]
    else:
        match = [t for t in rows if t.id == trial_id]
        if not match:
            return GateResult(
                approved=False,
                reasons=[f"Tentativa id={trial_id} não encontrada na família '{family_id}'."],
                costs_included=bool(costs_included),
                threshold=threshold,
            )
        trial = match[0]

    n_trials = float(registry.count(family_id))
    # The discarded B3 net-net search stays in the raw N of every later gate.
    # N_eff, when the family has return series, still describes only this family.
    if family_id != REJECTED_NET_NET_FAMILY:
        n_trials += float(registry.count(REJECTED_NET_NET_FAMILY))
    n_eff = None
    trial_sharpes = [t.sharpe for t in rows if t.sharpe is not None]
    try:
        eff = registry.effective_n_trials(family_id, method="average_correlation", cluster_corr=cluster_corr)
        n_eff = eff["n_eff"]
    except ValueError:
        n_eff = None

    stored_net = bool(trial.costs_included)
    net = bool(costs_included) and stored_net
    # Use N_eff with the theoretical SE, or raw N with the empirical
    # variance of trial Sharpes — not both, which would under-deflate.
    use_neff = bool(use_effective_n and n_eff is not None and n_eff >= 2)
    result = gate(
        costs_included=net,
        returns=trial.returns,
        observed_sharpe=None if trial.returns is not None else trial.sharpe,
        n_obs=None if trial.returns is not None else trial.n_obs,
        n_trials=n_trials,
        skew=0.0 if trial.returns is not None else (trial.skew or 0.0),
        excess_kurtosis=0.0 if trial.returns is not None else (trial.excess_kurtosis or 0.0),
        trial_sharpes=None if use_neff else (trial_sharpes if len(trial_sharpes) >= 2 else None),
        n_eff=n_eff if use_neff else None,
        threshold=threshold,
        periods_per_year=trial.periods_per_year,
    )
    if costs_included and not stored_net:
        result.reasons.insert(
            0,
            "A tentativa foi registrada sem a flag de retornos líquidos de custo; o gate recusa a promoção.",
        )
        result.approved = False
        result.costs_included = False
    result.n_trials = n_trials
    result.n_eff = n_eff
    return result
