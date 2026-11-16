"""Shared market-symbol validation.

Single source of truth for ticker/symbol path params. Symbols are used to
build upstream URLs, cache keys and log lines, so every public entry point
must reject path/query metacharacters (``/ ? # ..``) and bound the length
before the value flows anywhere else.
"""
from __future__ import annotations

import re

# Optional leading ^ (Yahoo index tickers like ^BVSP), then a letter (blocks
# leading dots/slashes); up to 25 chars. Mirrors the strictest connector in
# the tree (live_quotes Yahoo branch), plus the ^ index prefix.
SYMBOL_RE = re.compile(r"\^?[A-Z][A-Z0-9.\-^=]{0,24}")
SYMBOL_MAX_LENGTH = 25


def validate_symbol(value: str) -> str:
    """Normalise and validate a market symbol.

    Returns the upper-cased symbol. Raises ``ValueError`` on mismatch so
    both FastAPI dependencies (mapped to 422) and services (mapped to 400
    or ValueError) can share it.
    """
    if not isinstance(value, str):
        raise ValueError("symbol must be a string")
    symbol = value.strip().upper()
    if not SYMBOL_RE.fullmatch(symbol):
        raise ValueError(
            "invalid symbol: 1-25 chars, A-Z 0-9 . - ^ = (optional leading ^)"
        )
    return symbol
