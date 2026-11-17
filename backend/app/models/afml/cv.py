"""Purged K-Fold CV with embargo (sklearn compatible)."""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.model_selection import BaseCrossValidator


class PurgedKFold(BaseCrossValidator):
    """Contiguous K-fold that purges train samples whose [t0,t1] overlaps the test span
    and embargoes `pct_embargo` of samples right after each test fold.

    t1: Series indexed by t0 (sorted), values = label end time. X must share t1's index.
    """

    def __init__(self, n_splits: int = 5, t1: pd.Series | None = None, pct_embargo: float = 0.0):
        if t1 is None or not isinstance(t1, pd.Series):
            raise ValueError("t1 must be a pd.Series")
        self.n_splits, self.t1, self.pct_embargo = n_splits, t1, pct_embargo

    def get_n_splits(self, X=None, y=None, groups=None):
        return self.n_splits

    def split(self, X, y=None, groups=None):
        if hasattr(X, "index") and not X.index.equals(self.t1.index):
            raise ValueError("X and t1 must have the same index")
        n = len(self.t1)
        t0 = self.t1.index.to_numpy()
        t1 = self.t1.to_numpy()
        emb = int(n * self.pct_embargo)
        idx = np.arange(n)
        for test in np.array_split(idx, self.n_splits):
            a, b = test[0], test[-1]
            ts, te = t0[a], t1[test].max()
            overlap = (t0 <= te) & (t1 >= ts)
            emb_mask = np.zeros(n, dtype=bool)
            emb_mask[b + 1 : min(n, b + 1 + emb)] = True
            train = idx[~overlap & ~emb_mask]
            train = np.setdiff1d(train, test)
            yield train, test

    def _iter_test_indices(self, X=None, y=None, groups=None):  # pragma: no cover
        for _, t in self.split(X):
            yield t
