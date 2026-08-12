"""Terse builders shared by the suite.

Imported by plain name (`from conftest import line, factors, cascade`), not as
pytest fixtures — so each test reads in three lines.
"""

from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from motor_costos import (
    CostCascadeV1,
    CostFactors,
    DimensionCheckV1,
    ResourceLine,
    RoundingPolicy,
)

# A six-category taxonomy: material, labour, equipment, transport, tooling and
# subcontract. Declared by the caller in every test, never assumed by the engine.
REFERENCE_CATEGORIES = ("MAT", "MO", "EQ", "TR", "HE", "SC")
LABOUR = "MO"


def D(value: str | int) -> Decimal:  # noqa: N802 - one letter on purpose; see the module docstring
    return Decimal(str(value))


def line(
    category: str,
    quantity: str | int,
    unit_price: str | int,
    waste_pct: str | int = "0",
    currency: str = "USD",
    resource_id: str | None = None,
) -> ResourceLine:
    return ResourceLine(
        resource_id=resource_id or f"{category}-{quantity}-{unit_price}-{waste_pct}",
        category=category,
        quantity=D(quantity),
        unit_price=D(unit_price),
        waste_pct=D(waste_pct),
        currency=currency,
    )


def factors(
    tool_wear_pct: str | int = "0",
    safety_equipment_pct: str | int = "0",
    indirect_cost_pct: str | int = "0",
    financing_pct: str | int = "0",
    utility_pct: str | int = "0",
    tax_pct: str | int = "0",
) -> CostFactors:
    return CostFactors(
        tool_wear_pct=D(tool_wear_pct),
        safety_equipment_pct=D(safety_equipment_pct),
        indirect_cost_pct=D(indirect_cost_pct),
        financing_pct=D(financing_pct),
        utility_pct=D(utility_pct),
        tax_pct=D(tax_pct),
    )


def cascade(
    lines,
    cost_factors=None,
    categories=REFERENCE_CATEGORIES,
    labour_category: str = LABOUR,
    rounding: RoundingPolicy | None = None,
) -> CostCascadeV1:
    return CostCascadeV1(
        categories=tuple(categories),
        labour_category=labour_category,
        lines=tuple(lines),
        factors=cost_factors if cost_factors is not None else factors(),
        rounding=rounding if rounding is not None else RoundingPolicy(),
    )


def dimension(quantity_field: str, unit_category: str, unit_symbol: str | None = None):
    return DimensionCheckV1(
        quantity_field=quantity_field,
        unit_category=unit_category,
        unit_symbol=unit_symbol,
    )


def by_stage(result) -> dict[str, Decimal]:
    """Stage name -> amount, for assertions that name the stage."""
    return {stage.name: stage.amount for stage in result.stages}


def by_category(result) -> dict[str, Decimal]:
    return {entry.category: entry.cost for entry in result.categories}


def codes(result) -> list[int]:
    return [d.code for d in result.diagnostics]
