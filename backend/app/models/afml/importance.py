"""Feature importance: MDI, MDA (purged CV), SFI."""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.base import clone
from sklearn.metrics import accuracy_score, log_loss

from .cv import PurgedKFold


def mdi(fitted_forest, feature_names) -> pd.DataFrame:
    """Mean impurity decrease across trees (mean, std/sqrt(n)), normalized to sum 1.

    Fit forest with max_features=1 for less masking.
    """
    imp = np.array([t.feature_importances_ for t in fitted_forest.estimators_])
    imp[imp == 0] = np.nan
    df = pd.DataFrame(
        {"mean": np.nanmean(imp, 0), "std": np.nanstd(imp, 0) / np.sqrt(len(imp))},
        index=feature_names,
    )
    df["std"] /= df["mean"].sum()
    df["mean"] /= df["mean"].sum()
    return df.sort_values("mean", ascending=False)


def _score(clf, X, y, w, scoring):
    if scoring == "neg_log_loss":
        p = clf.predict_proba(X)
        return -log_loss(y, p, sample_weight=w, labels=clf.classes_)
    return accuracy_score(y, clf.predict(X), sample_weight=w)


def mda(clf, X: pd.DataFrame, y: pd.Series, cv: PurgedKFold, sample_weight=None,
        scoring="neg_log_loss", rng=0) -> pd.DataFrame:
    """Out-of-fold permutation importance: drop in score after shuffling each feature."""
    rng = np.random.default_rng(rng)
    w = np.ones(len(y)) if sample_weight is None else np.asarray(sample_weight)
    base, perm = [], {c: [] for c in X.columns}
    for tr, te in cv.split(X):
        m = clone(clf).fit(X.iloc[tr], y.iloc[tr], sample_weight=w[tr])
        Xt, yt, wt = X.iloc[te], y.iloc[te], w[te]
        s0 = _score(m, Xt, yt, wt, scoring)
        base.append(s0)
        for c in X.columns:
            xp = Xt.copy()
            xp[c] = rng.permutation(xp[c].to_numpy())
            perm[c].append(s0 - _score(m, xp, yt, wt, scoring))
    d = pd.DataFrame(perm)
    return pd.DataFrame({"mean": d.mean(), "std": d.std() / np.sqrt(len(d))}).sort_values("mean", ascending=False)


def sfi(clf, X, y, cv, sample_weight=None, scoring="neg_log_loss") -> pd.DataFrame:
    """Single-feature importance: OOF score of a model trained on each feature alone."""
    w = np.ones(len(y)) if sample_weight is None else np.asarray(sample_weight)
    out = {}
    for c in X.columns:
        sc = []
        for tr, te in cv.split(X):
            m = clone(clf).fit(X[[c]].iloc[tr], y.iloc[tr], sample_weight=w[tr])
            sc.append(_score(m, X[[c]].iloc[te], y.iloc[te], w[te], scoring))
        out[c] = (np.mean(sc), np.std(sc) / np.sqrt(len(sc)))
    return pd.DataFrame(out, index=["mean", "std"]).T.sort_values("mean", ascending=False)
