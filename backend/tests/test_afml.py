"""AFML bars, triple barrier, uniqueness, purged CV, importance."""
import numpy as np
import pandas as pd
import pytest
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import cross_val_score

from app.models.afml.bars import dollar_bars, volume_bars
from app.models.afml.cv import PurgedKFold
from app.models.afml.importance import mda, mdi, sfi
from app.models.afml.labeling import (
    cusum_filter,
    daily_volatility,
    get_bins,
    rolling_volatility,
    triple_barrier_events,
    vertical_barrier,
)
from app.models.afml.weights import (
    average_uniqueness,
    indicator_matrix,
    num_concurrent_events,
    return_attribution_weights,
    sequential_bootstrap,
    time_decay,
)

IDX = pd.date_range("2024-01-01", periods=10, freq="h")


def test_volume_bars_ticks():
    df = pd.DataFrame({"price": [1, 2, 3, 4, 5, 6], "volume": [1, 1, 1, 2, 3, 1]}, index=IDX[:6])
    b = volume_bars(df, 3)
    assert list(b["n_ticks"]) == [3, 2]
    assert list(b["open"]) == [1, 4] and list(b["close"]) == [3, 5] and list(b["high"]) == [3, 5]
    assert b.index[0] == IDX[2]


def test_dollar_bars_ticks_and_ohlcv():
    df = pd.DataFrame({"price": [10, 10, 20, 5], "volume": [1, 1, 1, 4]}, index=IDX[:4])
    b = dollar_bars(df, 20)
    assert list(b["n_ticks"]) == [2, 1, 1]
    o = pd.DataFrame(
        {"open": [1, 2, 3], "high": [2, 3, 4], "low": [1, 2, 3], "close": [2, 3, 4], "volume": [10, 10, 10]},
        index=IDX[:3],
    )
    b2 = dollar_bars(o, 40)
    assert b2["high"].iloc[0] == 3 and b2["low"].iloc[0] == 1 and b2["volume"].iloc[0] == 20


def test_volatility_no_lookahead():
    rng = np.random.default_rng(0)
    c = pd.Series(100 * np.exp(np.cumsum(rng.normal(0, .01, 300))), index=pd.date_range("2024", periods=300, freq="h"))
    v1 = rolling_volatility(c, span=50)
    c2 = c.copy()
    c2.iloc[200:] *= 3
    v2 = rolling_volatility(c2, span=50)
    pd.testing.assert_series_equal(v1.iloc[:200], v2.iloc[:200])
    dv = daily_volatility(c, span=20)
    assert dv.iloc[:24].isna().all() and dv.iloc[-1] > 0


def test_cusum():
    c = pd.Series([100, 101, 102, 103, 102, 101, 100, 99], index=IDX[:8], dtype=float)
    ev = cusum_filter(c, 0.025)
    assert list(ev) == [IDX[3], IDX[6]]


def _path(vals):
    return pd.Series(vals, index=pd.date_range("2024", periods=len(vals), freq="h"), dtype=float)


def test_triple_barrier_pt_sl_t1():
    c = _path([100, 101, 103, 99, 100, 100, 100])
    trg = pd.Series(0.02, index=c.index)
    t1 = vertical_barrier(c, [c.index[0]], num_bars=5)
    ev = triple_barrier_events(c, [c.index[0]], trg, (1, 1), t1=t1)
    assert ev["touch"].iloc[0] == "pt" and ev["t1"].iloc[0] == c.index[2]
    ev = triple_barrier_events(c, [c.index[0]], trg, (1, 1), t1=t1, side=pd.Series(-1, index=c.index))
    assert ev["touch"].iloc[0] == "sl" and ev["t1"].iloc[0] == c.index[2]
    flat = _path([100, 100.5, 100.2, 100.1, 100.3, 100.4, 100])
    t1f = vertical_barrier(flat, [flat.index[0]], num_bars=3)
    ev = triple_barrier_events(flat, [flat.index[0]], trg, (1, 1), t1=t1f)
    assert ev["touch"].iloc[0] == "t1" and ev["t1"].iloc[0] == flat.index[3]
    b = get_bins(ev, flat, meta=True)
    assert b["bin"].iloc[0] == 1 and np.isclose(b["ret"].iloc[0], 0.001)


def test_triple_barrier_ignores_t0_and_future_after_t1():
    c = _path([100, 100, 100, 100, 200])
    trg = pd.Series(0.05, index=c.index)
    t1 = vertical_barrier(c, [c.index[0]], num_bars=2)
    ev = triple_barrier_events(c, [c.index[0]], trg, (1, 1), t1=t1)
    assert ev["touch"].iloc[0] == "t1"
    ev2 = triple_barrier_events(c, [c.index[1]], trg, (0, 0), t1=None)
    assert ev2.empty


def test_meta_bins_net_of_cost():
    c = _path([100, 98, 96, 95])
    trg = pd.Series(0.03, index=c.index)
    ev = triple_barrier_events(
        c, [c.index[0]], trg, (1, 1), t1=vertical_barrier(c, [c.index[0]], 3),
        side=pd.Series(-1.0, index=c.index),
    )
    b = get_bins(ev, c, meta=True)
    assert ev["touch"].iloc[0] == "pt" and b["bin"].iloc[0] == 1 and b["ret"].iloc[0] > 0
    expensive = get_bins(ev, c, meta=True, cost=0.5)
    assert expensive["bin"].iloc[0] == 0
    assert np.isclose(expensive["ret_net"].iloc[0], b["ret"].iloc[0] - 0.5)


def test_concurrency_uniqueness():
    idx = pd.date_range("2024", periods=6, freq="h")
    t1 = pd.Series([idx[2], idx[3], idx[5]], index=[idx[0], idx[1], idx[4]])
    conc = num_concurrent_events(idx, t1)
    assert list(conc) == [1, 2, 2, 1, 1, 1]
    u = average_uniqueness(idx, t1)
    assert np.isclose(u.iloc[0], (1 + .5 + .5) / 3) and np.isclose(u.iloc[2], 1.0)
    w = return_attribution_weights(_path([1, 2, 4, 8, 8, 8]).set_axis(idx), t1)
    assert np.isclose(w.sum(), 3) and w.iloc[2] == 0


def test_time_decay():
    u = pd.Series([1.0, 1.0, 1.0, 1.0], index=pd.date_range("2024", periods=4, freq="h"))
    assert np.allclose(time_decay(u, 1), 1)
    d = time_decay(u, 0.5)
    assert d.is_monotonic_increasing and np.isclose(d.iloc[-1], 1)
    assert (time_decay(u, -0.5).iloc[:2] == 0).all()


def test_sequential_bootstrap_prefers_unique():
    idx = pd.date_range("2024", periods=6, freq="h")
    t1 = pd.Series([idx[2], idx[2], idx[5]], index=[idx[0], idx[1], idx[3]])
    t1.iloc[1] = idx[2]
    ind = indicator_matrix(idx, t1)
    cnt = np.zeros(3)
    for s in range(300):
        for j in sequential_bootstrap(ind, rng=s):
            cnt[j] += 1
    assert cnt[2] > cnt[0] and cnt[2] > cnt[1]


def test_purged_kfold_removes_overlap_and_embargo():
    idx = pd.date_range("2024", periods=100, freq="h")
    t1 = pd.Series(idx + pd.Timedelta(hours=5), index=idx)
    cv = PurgedKFold(5, t1, pct_embargo=0.03)
    x = pd.DataFrame({"a": range(100)}, index=idx)
    for tr, te in cv.split(x):
        ts, te_end = idx[te[0]], t1.iloc[te].max()
        assert not ((t1.index[tr] <= te_end) & (t1.iloc[tr] >= ts)).any()
        assert not set(tr) & set(te)
        if te[-1] < 99:
            assert not set(range(te[-1] + 1, min(100, te[-1] + 4))) & set(tr)
    y = pd.Series(np.arange(100) % 2, index=idx)
    s = cross_val_score(RandomForestClassifier(n_estimators=5, random_state=0), x, y, cv=cv)
    assert len(s) == 5


def test_importance_finds_signal():
    rng = np.random.default_rng(1)
    n = 600
    idx = pd.date_range("2024", periods=n, freq="h")
    x = pd.DataFrame(
        {"sig": rng.normal(size=n), "noise1": rng.normal(size=n), "noise2": rng.normal(size=n)},
        index=idx,
    )
    y = pd.Series((x["sig"] + 0.3 * rng.normal(size=n) > 0).astype(int), index=idx)
    t1 = pd.Series(idx + pd.Timedelta(hours=2), index=idx)
    cv = PurgedKFold(4, t1, 0.01)
    rf = RandomForestClassifier(n_estimators=50, max_features=1, random_state=0)
    assert mdi(rf.fit(x, y), x.columns).index[0] == "sig"
    assert mda(rf, x, y, cv).index[0] == "sig"
    assert sfi(rf, x, y, cv).index[0] == "sig"


def test_purged_kfold_requires_t1():
    with pytest.raises(ValueError, match="t1"):
        PurgedKFold(5, t1=None)
