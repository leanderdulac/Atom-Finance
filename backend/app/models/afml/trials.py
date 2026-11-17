"""Append-only registry of every strategy / parameter variant tested.

Persists to a SQLite file (path configurable). Count N per family, and
estimate the effective number of independent trials from stored return
series (average pairwise correlation, or hierarchical clustering).
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

from app.models.winners_curse import DEFAULT_PERIODS, sharpe_moments

SCHEMA = """
CREATE TABLE IF NOT EXISTS trials (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    family_id TEXT NOT NULL,
    params_hash TEXT NOT NULL,
    params_json TEXT,
    ts_utc TEXT NOT NULL,
    sharpe REAL,
    n_obs INTEGER,
    skew REAL,
    excess_kurtosis REAL,
    periods_per_year REAL NOT NULL DEFAULT 252,
    costs_included INTEGER NOT NULL DEFAULT 0,
    returns_json TEXT,
    notes TEXT
);
CREATE INDEX IF NOT EXISTS idx_trials_family ON trials(family_id);
"""


def hash_params(params: Any) -> str:
    """Stable SHA-256 of a params mapping (or of a preformatted string)."""
    if isinstance(params, str):
        payload = params
    else:
        payload = json.dumps(params, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _utcnow() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _mean_pairwise_corr(series: list[np.ndarray]) -> tuple[np.ndarray, float]:
    n = len(series)
    corr = np.eye(n, dtype=np.float64)
    for i in range(n):
        for j in range(i + 1, n):
            a, b = series[i], series[j]
            m = min(len(a), len(b))
            if m < 3 or float(np.std(a[:m], ddof=1)) < 1e-16 or float(np.std(b[:m], ddof=1)) < 1e-16:
                rho = 0.0
            else:
                rho = float(np.corrcoef(a[:m], b[:m])[0, 1])
            if not np.isfinite(rho):
                rho = 0.0
            corr[i, j] = corr[j, i] = rho
    rho_bar = float(corr[np.triu_indices(n, 1)].mean()) if n >= 2 else 0.0
    return corr, rho_bar


def _n_clusters(corr: np.ndarray, cluster_corr: float) -> int:
    """Average-linkage clusters; merge while pairwise corr ≥ `cluster_corr`."""
    from scipy.cluster.hierarchy import fcluster, linkage
    from scipy.spatial.distance import squareform

    n = corr.shape[0]
    if n <= 1:
        return n
    dist = np.clip(1.0 - corr, 0.0, 2.0)
    np.fill_diagonal(dist, 0.0)
    condensed = squareform(np.maximum(dist, dist.T), checks=False)
    if not np.any(condensed > 0):
        return 1
    z = linkage(condensed, method="average")
    labels = fcluster(z, t=max(1.0 - cluster_corr, 0.0), criterion="distance")
    return int(len(set(labels)))


def effective_independent_trials(
    return_series: Sequence[Sequence[float]],
    method: str = "average_correlation",
    cluster_corr: float = 0.5,
) -> dict[str, Any]:
    """N_eff from stored per-period return series.

    `average_correlation`: N / (1 + (N−1) max(ρ̄, 0)), ρ̄ = mean pairwise corr.
    `cluster`: number of average-linkage clusters cut at corr=`cluster_corr`.
    """
    series = [np.asarray(s, dtype=np.float64) for s in return_series]
    series = [s[np.isfinite(s)] for s in series]
    series = [s for s in series if len(s) >= 3]
    n = len(series)
    if n == 0:
        raise ValueError("Need at least one return series with ≥3 observations")
    if n == 1:
        return {"n": 1, "n_eff": 1.0, "mean_corr": 0.0, "method": method, "n_clusters": 1}
    corr, rho_bar = _mean_pairwise_corr(series)
    rho_clip = max(float(rho_bar), 0.0)
    n_eff_avg = n / (1.0 + (n - 1) * rho_clip)
    n_clusters = _n_clusters(corr, cluster_corr)
    if method == "average_correlation":
        n_eff = float(n_eff_avg)
    elif method == "cluster":
        n_eff = float(n_clusters)
    else:
        raise ValueError("method must be 'average_correlation' or 'cluster'")
    return {
        "n": n,
        "n_eff": n_eff,
        "mean_corr": rho_bar,
        "method": method,
        "n_clusters": n_clusters,
        "cluster_corr": cluster_corr,
    }


@dataclass
class Trial:
    id: int
    family_id: str
    params_hash: str
    params: Any
    ts_utc: str
    sharpe: float | None
    n_obs: int | None
    skew: float | None
    excess_kurtosis: float | None
    periods_per_year: float
    costs_included: bool
    returns: list[float] | None
    notes: str | None = None


class TrialRegistry:
    """Append-only SQLite log of backtest / research trials."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        if self.path.parent and not self.path.parent.exists():
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> TrialRegistry:
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def register(
        self,
        family_id: str,
        params: Any,
        *,
        returns: Sequence[float] | None = None,
        sharpe: float | None = None,
        n_obs: int | None = None,
        skew: float | None = None,
        excess_kurtosis: float | None = None,
        costs_included: bool = False,
        periods_per_year: float = DEFAULT_PERIODS,
        notes: str | None = None,
        timestamp: str | None = None,
    ) -> Trial:
        """Append one trial. If `returns` is given, Sharpe / T / moments are computed from it."""
        if not family_id:
            raise ValueError("family_id is required")
        returns_list = None
        if returns is not None:
            r = np.asarray(returns, dtype=np.float64)
            returns_list = [float(x) for x in r]
            m = sharpe_moments(r, periods_per_year)
            sharpe = m["observed_sharpe"]
            n_obs = int(m["n_obs"])
            skew = m["skew"]
            excess_kurtosis = m["excess_kurtosis"]
        elif sharpe is None or n_obs is None:
            raise ValueError("Provide `returns`, or both `sharpe` and `n_obs`")
        if skew is None:
            skew = 0.0
        if excess_kurtosis is None:
            excess_kurtosis = 0.0

        params_json = None if isinstance(params, str) else json.dumps(params, sort_keys=True, default=str)
        ph = hash_params(params)
        ts = timestamp or _utcnow()
        cur = self._conn.execute(
            """INSERT INTO trials(
                    family_id, params_hash, params_json, ts_utc, sharpe, n_obs,
                    skew, excess_kurtosis, periods_per_year, costs_included,
                    returns_json, notes
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                family_id,
                ph,
                params_json,
                ts,
                None if sharpe is None else float(sharpe),
                None if n_obs is None else int(n_obs),
                float(skew),
                float(excess_kurtosis),
                float(periods_per_year),
                1 if costs_included else 0,
                None if returns_list is None else json.dumps(returns_list),
                notes,
            ),
        )
        self._conn.commit()
        return Trial(
            id=int(cur.lastrowid),
            family_id=family_id,
            params_hash=ph,
            params=params if params_json is None else json.loads(params_json),
            ts_utc=ts,
            sharpe=None if sharpe is None else float(sharpe),
            n_obs=None if n_obs is None else int(n_obs),
            skew=float(skew),
            excess_kurtosis=float(excess_kurtosis),
            periods_per_year=float(periods_per_year),
            costs_included=bool(costs_included),
            returns=returns_list,
            notes=notes,
        )

    def count(self, family_id: str | None = None) -> int:
        if family_id is None:
            row = self._conn.execute("SELECT COUNT(*) FROM trials").fetchone()
        else:
            row = self._conn.execute(
                "SELECT COUNT(*) FROM trials WHERE family_id = ?", (family_id,)
            ).fetchone()
        return int(row[0])

    def trials(self, family_id: str | None = None) -> list[Trial]:
        if family_id is None:
            rows = self._conn.execute("SELECT * FROM trials ORDER BY id ASC").fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM trials WHERE family_id = ? ORDER BY id ASC", (family_id,)
            ).fetchall()
        return [self._row(r) for r in rows]

    def effective_n_trials(
        self,
        family_id: str,
        method: str = "average_correlation",
        cluster_corr: float = 0.5,
    ) -> dict[str, Any]:
        rows = [t for t in self.trials(family_id) if t.returns and len(t.returns) >= 3]
        if not rows:
            raise ValueError(
                f"Family '{family_id}' has no stored return series; cannot estimate N_eff"
            )
        out = effective_independent_trials(
            [t.returns for t in rows], method=method, cluster_corr=cluster_corr
        )
        out["family_id"] = family_id
        out["n_registered"] = self.count(family_id)
        return out

    def _row(self, r: tuple) -> Trial:
        (
            tid, family_id, params_hash, params_json, ts_utc, sharpe, n_obs,
            skew, excess_kurtosis, periods_per_year, costs_included, returns_json, notes,
        ) = r
        params = json.loads(params_json) if params_json else params_hash
        returns = json.loads(returns_json) if returns_json else None
        return Trial(
            id=int(tid),
            family_id=family_id,
            params_hash=params_hash,
            params=params,
            ts_utc=ts_utc,
            sharpe=None if sharpe is None else float(sharpe),
            n_obs=None if n_obs is None else int(n_obs),
            skew=None if skew is None else float(skew),
            excess_kurtosis=None if excess_kurtosis is None else float(excess_kurtosis),
            periods_per_year=float(periods_per_year),
            costs_included=bool(costs_included),
            returns=returns,
            notes=notes,
        )
