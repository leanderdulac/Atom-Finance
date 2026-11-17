"""Concurrency, uniqueness, sample weights and sequential bootstrap."""

from __future__ import annotations

import numpy as np
import pandas as pd


def num_concurrent_events(close_index: pd.Index, t1: pd.Series) -> pd.Series:
    """Number of labels whose [t0, t1] span covers each bar."""
    t1 = t1.fillna(close_index[-1])
    s = close_index.searchsorted(t1.index)
    e = close_index.searchsorted(t1.to_numpy(), side="right")
    diff = np.zeros(len(close_index) + 1)
    np.add.at(diff, s, 1)
    np.add.at(diff, e, -1)
    cnt = np.cumsum(diff)[:-1]
    return pd.Series(cnt, index=close_index)


def average_uniqueness(close_index: pd.Index, t1: pd.Series, conc: pd.Series | None = None) -> pd.Series:
    conc = num_concurrent_events(close_index, t1) if conc is None else conc
    t1 = t1.fillna(close_index[-1])
    inv = 1.0 / conc.replace(0, np.nan)
    out = {t0: inv.loc[t0:te].mean() for t0, te in t1.items()}
    return pd.Series(out)


def return_attribution_weights(close: pd.Series, t1: pd.Series, conc: pd.Series | None = None) -> pd.Series:
    """|sum_t r_t / c_t| over the label span, normalized to sum to len(t1)."""
    conc = num_concurrent_events(close.index, t1) if conc is None else conc
    t1 = t1.fillna(close.index[-1])
    lr = np.log(close).diff().fillna(0)
    x = lr / conc.replace(0, np.nan)
    w = pd.Series({t0: abs(x.loc[t0:te].iloc[1:].sum()) for t0, te in t1.items()})
    tot = w.sum()
    return w * len(w) / tot if tot > 0 else pd.Series(1.0, index=w.index)


def time_decay(uniqueness: pd.Series, c: float = 1.0) -> pd.Series:
    """Linear decay on cumulative uniqueness. c=1 no decay; 0<c<1 oldest gets c; c<0 oldest share zeroed."""
    cum = uniqueness.sort_index().cumsum()
    last = cum.iloc[-1]
    slope = (1 - c) / last if c >= 0 else 1 / ((c + 1) * last)
    const = 1 - slope * last
    return (const + slope * cum).clip(lower=0)


def indicator_matrix(bar_index: pd.Index, t1: pd.Series) -> pd.DataFrame:
    t1 = t1.fillna(bar_index[-1])
    m = pd.DataFrame(0.0, index=bar_index, columns=range(len(t1)))
    for j, (t0, te) in enumerate(t1.items()):
        m.loc[t0:te, j] = 1.0
    return m


def sequential_bootstrap(ind: pd.DataFrame, s_length: int | None = None, rng=None) -> list:
    """Draw samples with probability proportional to their average uniqueness given draws so far."""
    rng = np.random.default_rng(rng)
    M = ind.to_numpy()
    n = M.shape[1]
    s_length = n if s_length is None else s_length
    c = np.zeros(M.shape[0])
    phi = []
    active = M > 0
    for _ in range(s_length):
        u = np.array([(1.0 / (c[active[:, j]] + 1)).mean() for j in range(n)])
        j = rng.choice(n, p=u / u.sum())
        phi.append(int(j))
        c += M[:, j]
    return phi
