"""Unit tests for security validation helpers (no DB required)."""
import csv
import io

import pytest
from pydantic import ValidationError
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.api.portfolio import PortfolioRequest
from app.api.pricing import IVRequest, PricingRequest, SurfaceRequest
from app.api.reports import _flatten, _safe_cell, _safe_filename
from app.api.risk import VaRRequest
from app.core.observability import request_id_middleware, request_id_var
from app.core.security import _clamped_int_env, is_production
from app.core.symbols import validate_symbol
from app.db.maintenance import _passwordless_url_and_env


class TestValidateSymbol:
    @pytest.mark.parametrize("raw,expected", [
        ("petr4", "PETR4"),
        ("  aapl ", "AAPL"),
        ("BTC-USD", "BTC-USD"),
        ("PETR4.SA", "PETR4.SA"),
        ("^BVSP", "^BVSP"),
        ("BRK.B", "BRK.B"),
    ])
    def test_accepts_known_shapes(self, raw, expected):
        assert validate_symbol(raw) == expected

    @pytest.mark.parametrize("raw", [
        "", "   ", "../secret", "a/b", "a?b=1", "a#b", "a b", "a;b", "a|b",
        "a" * 26, "1ABC", "-ABC", ".ABC", "AB$C", "AB%C", "áé",
        123, None, b"PETR4",
    ])
    def test_rejects_path_confusion_and_overlong(self, raw):
        with pytest.raises(ValueError):
            validate_symbol(raw)


class TestSafeFilename:
    def test_strips_crlf_and_quotes(self):
        header = _safe_filename("Q3 Earnings\r\nBcc: evil@x.com", "csv")
        assert "\r" not in header and "\n" not in header
        assert header.startswith('attachment; filename="')
        assert "filename*=UTF-8''" in header

    def test_allows_benign_titles(self):
        header = _safe_filename("ATOM Analysis Report", "csv")
        assert 'filename="ATOM_Analysis_Report.csv"' in header

    def test_falls_back_on_empty(self):
        assert 'filename="report.csv"' in _safe_filename("...", "csv")


class TestSafeCell:
    @pytest.mark.parametrize("value", ["=cmd|'/c calc'!A1", "+1+1", "-2+3", "@SUM(A1)", "\tindented"])
    def test_neutralises_formula_cells(self, value):
        assert _safe_cell(value) == "'" + value

    @pytest.mark.parametrize("value", ["PETR4", 123, 4.5, None, "", " a=b "])
    def test_leaves_benign_cells_alone(self, value):
        assert _safe_cell(value) == value


class TestFlattenCaps:
    def test_rejects_deep_nesting(self):
        from fastapi import HTTPException

        deep: dict = {}
        cursor = deep
        for i in range(10):
            cursor["n"] = {}
            cursor = cursor["n"]
        with pytest.raises(HTTPException):
            _flatten(csv.writer(io.StringIO()), deep)

    def test_rejects_key_flood(self):
        from fastapi import HTTPException

        with pytest.raises(HTTPException):
            _flatten(csv.writer(io.StringIO()), {f"k{i}": i for i in range(6000)})

    def test_flat_report_passes(self):
        buf = io.StringIO()
        _flatten(csv.writer(buf), {"a": 1, "b": {"c": "=1+1"}})
        assert "'=1+1" in buf.getvalue()


class TestRequestIdAllowlist:
    @staticmethod
    def _request_with(headers: dict) -> Request:
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
        }
        return Request(scope)

    @pytest.mark.asyncio
    async def test_accepts_clean_id(self):
        seen = {}

        async def call_next(request):
            seen["id"] = request_id_var.get()
            return JSONResponse({})

        req = self._request_with({"X-Request-ID": "trace-abc-123"})
        resp = await request_id_middleware(req, call_next)
        assert seen["id"] == "trace-abc-123"
        assert resp.headers["X-Request-ID"] == "trace-abc-123"

    @pytest.mark.asyncio
    async def test_replaces_crlf_injection_with_uuid(self):
        seen = {}

        async def call_next(request):
            seen["id"] = request_id_var.get()
            return JSONResponse({})

        req = self._request_with({"X-Request-ID": "a\r\nX-Injected: 1"})
        resp = await request_id_middleware(req, call_next)
        assert "\r" not in seen["id"] and "\n" not in seen["id"]
        assert resp.headers["X-Request-ID"] == seen["id"]
        assert len(seen["id"]) == 36  # fresh UUID


class TestJwtTtlClamp:
    def test_defaults_within_bounds(self, monkeypatch):
        monkeypatch.delenv("ACCESS_TOKEN_EXPIRE_MINUTES", raising=False)
        assert _clamped_int_env("ACCESS_TOKEN_EXPIRE_MINUTES", 30, 5, 120) == 30

    @pytest.mark.parametrize("value", ["0", "-5", "1000000", "notanint"])
    def test_rejects_out_of_bounds(self, monkeypatch, value):
        monkeypatch.setenv("ACCESS_TOKEN_EXPIRE_MINUTES", value)
        with pytest.raises(RuntimeError):
            _clamped_int_env("ACCESS_TOKEN_EXPIRE_MINUTES", 30, 5, 120)


class TestIsProduction:
    @pytest.mark.parametrize("value", ["production", "Production", " PRODUCTION "])
    def test_matches_case_insensitive(self, monkeypatch, value):
        monkeypatch.setenv("ATOM_ENV", value)
        assert is_production() is True

    @pytest.mark.parametrize("value", ["development", "test", "staging", ""])
    def test_rejects_other_envs(self, monkeypatch, value):
        monkeypatch.setenv("ATOM_ENV", value)
        assert is_production() is False


class TestPasswordlessUrl:
    def test_splits_password_into_pgpassword(self, monkeypatch):
        monkeypatch.setenv(
            "ATOM_DATABASE_URL", "postgresql+asyncpg://atom:s3cr3t@db:5432/atom"
        )
        url, env = _passwordless_url_and_env()
        assert "s3cr3t" not in url
        assert url == "postgresql://atom@db:5432/atom"
        assert env["PGPASSWORD"] == "s3cr3t"

    def test_missing_url_raises(self, monkeypatch):
        monkeypatch.delenv("ATOM_DATABASE_URL", raising=False)
        with pytest.raises(RuntimeError):
            _passwordless_url_and_env()


class TestFiniteNumericSchemas:
    """NaN/Inf must fail request validation (422), never reach the engines."""

    def test_pricing_rejects_nonfinite(self):
        base = {"spot": 100, "strike": 100, "maturity": 1.0}
        PricingRequest(**base)  # sane baseline passes
        for bad in (float("nan"), float("inf"), float("-inf")):
            with pytest.raises(ValidationError):
                PricingRequest(**{**base, "sigma": bad})
            with pytest.raises(ValidationError):
                PricingRequest(**{**base, "rate": bad})

    def test_iv_and_surface_reject_nonfinite(self):
        with pytest.raises(ValidationError):
            IVRequest(market_price=float("inf"), spot=100, strike=100, maturity=1.0)
        with pytest.raises(ValidationError):
            SurfaceRequest(spot=100, strikes=[90, float("nan")])

    def test_var_and_portfolio_reject_nonfinite_series(self):
        with pytest.raises(ValidationError):
            VaRRequest(returns=[0.01] * 29 + [float("inf")])
        with pytest.raises(ValidationError):
            PortfolioRequest(returns=[[0.01, float("nan")]] * 30)
