"""The rounding policy, explicit and parametrisable. See ADR 0001.

Three facts drive this module.

The implementation this was translated from never rounds inside the cascade: it hands a
full-precision Decimal to its database and lets the column scale do the rounding. Its one
full-cascade oracle keeps seven decimals to the end. So exact intermediates are the
faithful translation, and writing the policy down is the point of extracting it.

Where that domain does round, the mode is ROUND_HALF_UP, pinned with ties that banker's
rounding would resolve the other way. So half-up is the only mode offered.

Money is stored at four decimals throughout the domain. So four is the default scale.
"""

from __future__ import annotations

import decimal
from collections.abc import Iterator
from contextlib import contextmanager
from decimal import ROUND_HALF_UP, Decimal

from motor_costos.models import RoundingPolicy

#: Significant digits every computation runs at.
#:
#: 28 is CPython's default, which is the precision the translated implementation
#: effectively used, so `exact` mode reproduces it even where a division is inexact.
#: Pinning it here
#: rather than inheriting the caller's context is what makes the determinism promise
#: true: a caller that lowers `decimal.getcontext().prec` must not be able to move the
#: answer. It is also the ceiling that bounds intermediate growth in `exact` mode.
ENGINE_PRECISION = 28

ROUNDING_MODES = ("exact", "final", "per-stage")


@contextmanager
def engine_context() -> Iterator[decimal.Context]:
    """Run arithmetic at a fixed precision, isolated from the caller's context."""
    with decimal.localcontext() as ctx:
        ctx.prec = ENGINE_PRECISION
        ctx.rounding = ROUND_HALF_UP
        yield ctx


class Rounder:
    """Applies a `RoundingPolicy` at the two points where it can be applied."""

    __slots__ = ("_exponent", "_per_stage", "_quantise_final")

    def __init__(self, policy: RoundingPolicy) -> None:
        self._exponent = Decimal(1).scaleb(-policy.money_scale)
        self._per_stage = policy.mode == "per-stage"
        self._quantise_final = policy.mode in ("final", "per-stage")

    def _quantise(self, value: Decimal) -> Decimal:
        return value.quantize(self._exponent, rounding=ROUND_HALF_UP)

    def stage(self, value: Decimal) -> Decimal:
        """Applied to every cascade stage; a no-op unless the mode is `per-stage`."""
        return self._quantise(value) if self._per_stage else value

    def final(self, value: Decimal) -> Decimal:
        """Applied to the unit cost; a no-op only in `exact` mode."""
        return self._quantise(value) if self._quantise_final else value
