"""Calibration: GBM recovers its level, purge spacing, degenerate input."""
import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.desk import router as desk_router
from app.core.limiter import limiter
from app.core.security import get_current_user
from app.models.calibration import interval_coverage


def _gbm(n, sigma=0.3, seed=0):
    rng = np.random.default_rng(seed)
    rets = rng.normal(-0.5 * sigma**2 / 252, sigma / np.sqrt(252), size=n)
    return (100.0 * np.exp(np.cumsum(rets))).tolist()


def test_gbm_recovers_nominal_coverage():
    out = interval_coverage(_gbm(3000, sigma=0.3), horizon_days=5)
    assert out["n_blocks"] > 100
    assert 0.80 <= out["coverage"] <= 0.97
    assert out["within_band"] is True


def test_level_is_respected():
    out = interval_coverage(_gbm(3000, sigma=0.2, seed=4), horizon_days=10, level=0.8)
    assert 0.68 <= out["coverage"] <= 0.90
    assert out["target_level"] == 0.8


def test_blocks_do_not_overlap():
    out = interval_coverage(_gbm(500), horizon_days=7)
    starts = out["block_starts"]
    gaps = np.diff(starts)
    assert (gaps == 7).all()
    assert out["n_blocks"] == len(starts) >= 2


def test_constant_series_degenerates_without_crashing():
    out = interval_coverage([100.0] * 300, horizon_days=5)
    assert out["mean_width"] == 0.0
    assert out["coverage"] == 1.0


def test_rejects_bad_input():
    with pytest.raises(ValueError, match="at least"):
        interval_coverage([100.0] * 50, horizon_days=5)
    with pytest.raises(ValueError, match="horizon_days"):
        interval_coverage(_gbm(500), horizon_days=100)
    with pytest.raises(ValueError, match="vol_lambda"):
        interval_coverage(_gbm(500), horizon_days=5, vol_lambda=1.5)
    with pytest.raises(ValueError, match="level"):
        interval_coverage(_gbm(500), horizon_days=5, level=0.4)
    bad = _gbm(500)
    bad[100] = -3.0
    with pytest.raises(ValueError, match="positive"):
        interval_coverage(bad, horizon_days=5)


def _client(monkeypatch):
    from slowapi import _rate_limit_exceeded_handler
    from slowapi.errors import RateLimitExceeded

    limiter.reset()
    app = FastAPI()
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.include_router(desk_router, prefix="/t")
    app.dependency_overrides[get_current_user] = lambda: "alice"
    return TestClient(app, raise_server_exceptions=False)


def test_endpoint_returns_coverage(monkeypatch):
    client = _client(monkeypatch)
    res = client.post("/t/calibration/coverage",
                      json={"prices": _gbm(800, seed=9), "horizon_days": 5})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["n_blocks"] > 50
    assert 0.75 <= body["coverage"] <= 0.98
    assert body["what_broke"]


def test_endpoint_validates_input(monkeypatch):
    client = _client(monkeypatch)
    assert client.post("/t/calibration/coverage",
                       json={"prices": [100.0] * 10}).status_code == 422
    res = client.post("/t/calibration/coverage",
                      json={"prices": [100.0] * 200, "horizon_days": 100})
    assert res.status_code == 422
