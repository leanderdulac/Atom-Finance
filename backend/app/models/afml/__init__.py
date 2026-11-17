"""AFML-inspired research tools for ATOM: labels, purged CV, trial log, DSR gate.

PSR / DSR / MinTRL live in ``app.models.winners_curse`` and are re-exported
here so the promotion gate never forks the Bailey–López de Prado formulae.
"""

from app.models.winners_curse import (
    annualized_sharpe,
    deflated_sharpe,
    expected_max_sharpe,
    min_track_record_length,
    probabilistic_sharpe,
    sharpe_moments,
)

from .gate import GateResult, gate, gate_trial
from .trials import Trial, TrialRegistry, effective_independent_trials, hash_params

__version__ = "0.2.0"
__all__ = [
    "GateResult",
    "Trial",
    "TrialRegistry",
    "annualized_sharpe",
    "deflated_sharpe",
    "effective_independent_trials",
    "expected_max_sharpe",
    "gate",
    "gate_trial",
    "hash_params",
    "min_track_record_length",
    "probabilistic_sharpe",
    "sharpe_moments",
]
