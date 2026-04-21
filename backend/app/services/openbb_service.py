"""OpenBB integration service.

This module integrates the OpenBB Platform as an optional market-data backend.
It uses lazy imports so the app still works when OpenBB is not installed.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
import logging
from typing import Any, Dict, List, Optional

import pandas as pd

logger = logging.getLogger(__name__)

_obb = None


def _prepare_openbb_provider_interface() -> None:
    """Patch OpenBB provider-interface exports for runtime compatibility."""
    try:
        import openbb_core.app.provider_interface as provider_interface  # type: ignore
        from openbb_core.app.provider_interface import ProviderInterface  # type: ignore

        for name, annotation in ProviderInterface().return_annotations.items():
            alias = f"OBBject_{name}"
            if not hasattr(provider_interface, alias):
                setattr(provider_interface, alias, annotation)
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("OpenBB provider interface patch skipped: %s", exc)


def _get_openbb():
    """Lazy-load the OpenBB SDK."""
    global _obb
    if _obb is None:
        try:
            _prepare_openbb_provider_interface()
            from openbb import obb  # type: ignore

            _obb = obb
        except ImportError:
            logger.warning("OpenBB is not installed. Install with: pip install openbb")
            return None
        except Exception as exc:  # pragma: no cover - defensive
            logger.error("Failed to load OpenBB: %s", exc)
            return None
    return _obb


class OpenBBService:
    """Optional OpenBB-backed market data provider."""

    @staticmethod
    def is_available() -> bool:
        return _get_openbb() is not None

    @staticmethod
    def provider_map() -> Dict[str, str]:
        return {
            "quote": "yfinance",
            "historical": "yfinance",
            "profile": "yfinance",
            "search": "sec",
            "options": "cboe",
        }

    @staticmethod
    def _output_to_dataframe(output: Any) -> pd.DataFrame:
        """Best-effort conversion from an OpenBB output to a DataFrame."""
        if output is None:
            return pd.DataFrame()

        for method_name in ("to_df", "to_dataframe"):
            method = getattr(output, method_name, None)
            if callable(method):
                try:
                    df = method()
                    if isinstance(df, pd.DataFrame):
                        return df
                except Exception:
                    pass

        results = getattr(output, "results", output)

        if isinstance(results, pd.DataFrame):
            return results
        if isinstance(results, list):
            normalized: List[Dict[str, Any]] = []
            for item in results:
                if hasattr(item, "model_dump"):
                    normalized.append(item.model_dump())
                elif isinstance(item, dict):
                    normalized.append(item)
            return pd.DataFrame(normalized)
        if hasattr(results, "model_dump"):
            payload = results.model_dump()
            try:
                return pd.DataFrame(payload)
            except Exception:
                return pd.DataFrame([payload])
        if isinstance(results, dict):
            try:
                return pd.DataFrame(results)
            except Exception:
                return pd.DataFrame([results])

        return pd.DataFrame()

    @classmethod
    def get_quote(cls, symbol: str, provider: str = "yfinance") -> Optional[Dict[str, Any]]:
        obb = _get_openbb()
        if obb is None:
            return None

        try:
            output = obb.equity.price.quote(symbol=symbol.upper(), provider=provider)
            df = cls._output_to_dataframe(output)
            if df.empty:
                return None

            row = df.iloc[0].to_dict()
            price = row.get("last_price") or row.get("currentPrice") or row.get("price") or row.get("close")
            prev_close = row.get("prev_close") or row.get("previousClose") or row.get("previous_close")
            change = row.get("change")
            if change is None and price is not None and prev_close not in (None, 0):
                change = float(price) - float(prev_close)

            change_pct = row.get("change_percent") or row.get("percent_change")
            if change_pct is None and change is not None and prev_close not in (None, 0):
                change_pct = (float(change) / float(prev_close)) * 100

            return {
                "ticker": symbol.upper(),
                "name": row.get("name"),
                "price": float(price) if price is not None else 0.0,
                "change": float(change) if change is not None else 0.0,
                "change_pct": float(change_pct) if change_pct is not None else 0.0,
                "volume": int(row.get("volume") or 0),
                "open": float(row.get("open") or 0),
                "high": float(row.get("high") or 0),
                "low": float(row.get("low") or 0),
                "bid": float(row.get("bid") or 0),
                "ask": float(row.get("ask") or 0),
                "prev_close": float(prev_close) if prev_close is not None else 0.0,
                "year_high": float(row.get("year_high") or row.get("fiftyTwoWeekHigh") or 0),
                "year_low": float(row.get("year_low") or row.get("fiftyTwoWeekLow") or 0),
                "provider": f"openbb::{provider}",
                "source": "openbb",
                "timestamp": datetime.now().isoformat(),
            }
        except Exception as exc:
            logger.warning("OpenBB quote failed for %s via %s: %s", symbol, provider, exc)
            return None

    @classmethod
    def get_historical_data(
        cls,
        symbol: str,
        provider: str = "yfinance",
        interval: str = "1d",
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> Optional[pd.DataFrame]:
        obb = _get_openbb()
        if obb is None:
            return None

        try:
            if start_date is None:
                start_date = (date.today() - timedelta(days=365)).isoformat()
            if end_date is None:
                end_date = date.today().isoformat()

            output = obb.equity.price.historical(
                symbol=symbol.upper(),
                provider=provider,
                interval=interval,
                start_date=start_date,
                end_date=end_date,
            )
            df = cls._output_to_dataframe(output)
            if df.empty:
                return None

            df = df.copy()
            if "date" in df.columns:
                df["date"] = pd.to_datetime(df["date"])
                df = df.sort_values("date")
                df = df.set_index("date")
            return df
        except Exception as exc:
            logger.warning("OpenBB history failed for %s via %s: %s", symbol, provider, exc)
            return None

    @classmethod
    def get_profile(cls, symbol: str, provider: str = "yfinance") -> Optional[Dict[str, Any]]:
        obb = _get_openbb()
        if obb is None:
            return None

        try:
            output = obb.equity.profile(symbol=symbol.upper(), provider=provider)
            df = cls._output_to_dataframe(output)
            if df.empty:
                return None
            row = df.iloc[0].to_dict()
            return {
                "symbol": symbol.upper(),
                "name": row.get("name"),
                "sector": row.get("sector"),
                "industry": row.get("industry") or row.get("industry_category"),
                "exchange": row.get("stock_exchange") or row.get("exchange"),
                "currency": row.get("currency"),
                "employees": row.get("employees"),
                "market_cap": row.get("market_cap"),
                "website": row.get("company_url") or row.get("website"),
                "description": row.get("long_description") or row.get("description"),
                "provider": f"openbb::{provider}",
                "source": "openbb",
            }
        except Exception as exc:
            logger.warning("OpenBB profile failed for %s via %s: %s", symbol, provider, exc)
            return None

    @classmethod
    def search_equity(cls, query: str, provider: str = "sec") -> List[Dict[str, Any]]:
        obb = _get_openbb()
        if obb is None:
            return []

        providers = [provider] + [candidate for candidate in ("sec", "cboe") if candidate != provider]

        for active_provider in providers:
            try:
                output = obb.equity.search(query=query, provider=active_provider, is_symbol=False, use_cache=True)
                df = cls._output_to_dataframe(output)
                if df.empty:
                    continue
                records = df.head(10).to_dict("records")
                for record in records:
                    record["provider"] = f"openbb::{active_provider}"
                    record["source"] = "openbb"
                return records
            except Exception as exc:
                logger.warning("OpenBB search failed for %s via %s: %s", query, active_provider, exc)

        return []

    @classmethod
    def get_options_chain(cls, symbol: str, provider: str = "cboe") -> Optional[Dict[str, Any]]:
        obb = _get_openbb()
        if obb is None:
            return None

        try:
            output = obb.derivatives.options.chains(symbol.upper(), provider=provider)
            df = cls._output_to_dataframe(output)
            if df.empty:
                return None

            normalized = df.copy()
            if "expiration" in normalized.columns:
                normalized["expiration"] = pd.to_datetime(normalized["expiration"]).dt.strftime("%Y-%m-%d")

            chain: List[Dict[str, Any]] = []
            grouped = normalized.groupby(["expiration", "strike"], dropna=False)
            for (expiration, strike), group in grouped:
                row: Dict[str, Any] = {
                    "expiration": expiration,
                    "strike": float(strike) if strike is not None else 0.0,
                    "volume": int(group.get("volume", pd.Series([0])).fillna(0).sum()),
                    "open_interest": int(group.get("open_interest", pd.Series([0])).fillna(0).sum()),
                }
                for _, option in group.iterrows():
                    option_type = str(option.get("option_type", "")).lower()
                    prefix = "call" if option_type == "call" else "put"
                    row[f"{prefix}_price"] = float(
                        option.get("last_trade_price")
                        or option.get("mark")
                        or option.get("lastPrice")
                        or option.get("bid")
                        or 0
                    )
                    row[f"{prefix}_delta"] = float(option.get("delta") or 0)
                    row[f"{prefix}_iv"] = float(
                        option.get("implied_volatility")
                        or option.get("mark_iv")
                        or option.get("impliedVolatility")
                        or 0
                    )
                chain.append(row)

            expirations = sorted({row["expiration"] for row in chain if row.get("expiration")})
            spot = None
            if "underlying_price" in normalized.columns and not normalized["underlying_price"].dropna().empty:
                spot = float(normalized["underlying_price"].dropna().iloc[0])

            return {
                "ticker": symbol.upper(),
                "spot": spot,
                "expirations": expirations,
                "chain": chain,
                "provider": f"openbb::{provider}",
                "source": "openbb",
            }
        except Exception as exc:
            logger.warning("OpenBB options failed for %s via %s: %s", symbol, provider, exc)
            return None

    @classmethod
    def get_provider_status(cls) -> Dict[str, Any]:
        return {
            "openbb_available": cls.is_available(),
            "default_openbb_providers": cls.provider_map(),
        }
