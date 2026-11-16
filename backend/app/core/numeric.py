"""Shared numeric field types with finite-value guards.

Pydantic v2 accepts inf/nan for plain `float`, and `gt=0` does not reject
+inf — so every public numeric schema must opt out explicitly. These aliases
are the single place to do it: use them for all user-supplied floats instead
of bare `float` + ad-hoc bounds.
"""
from __future__ import annotations

from typing import Annotated

from pydantic import Field

FiniteFloat = Annotated[float, Field(allow_inf_nan=False)]
PositiveFloat = Annotated[float, Field(gt=0, allow_inf_nan=False)]
NonNegativeFloat = Annotated[float, Field(ge=0, allow_inf_nan=False)]
FiniteFloatList = Annotated[list[float], Field(allow_inf_nan=False)]
