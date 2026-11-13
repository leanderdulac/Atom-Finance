"""Shared request-size limits for numeric endpoints.

Every series below is bounded so a single authenticated request cannot pin the
(single) uvicorn worker for minutes — several fits are pure-Python loops over
the observations (e.g. the Student-t copula likelihood over a ν grid). NaN/inf
are rejected at the schema layer: they otherwise propagate into results that
FastAPI cannot JSON-encode, surfacing as opaque 500s.
"""
from typing import Annotated

from pydantic import Field

FiniteFloat = Annotated[float, Field(allow_inf_nan=False)]

MAX_SERIES = 20_000       # ~80 years of daily data
MAX_ASSETS = 100

Series = Annotated[list[FiniteFloat], Field(max_length=MAX_SERIES)]
Row = Annotated[list[FiniteFloat], Field(min_length=1, max_length=MAX_ASSETS)]
Matrix = Annotated[list[Row], Field(max_length=MAX_SERIES)]
