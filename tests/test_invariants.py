"""Invariants translated from SQL CheckConstraints to engine validation.

The implementation this was translated from expresses its domain invariants as database
constraints. An engine has no database, so each one becomes either a type bound (rejected
when the contract is built) or a typed diagnostic (returned by the computation).

| SQL constraint                        | Here                |
|---------------------------------------|---------------------|
| six `pct BETWEEN 0 AND 100`           | `Field(ge, le)`     |
| `quantity > 0`                        | `Field(gt=0)`       |
| `waste_pct BETWEEN 0 AND 100`         | `Field(ge, le)`     |
| `unit_price_override IS NULL OR >= 0` | `Field(ge=0)`       |
| unique resource per composition       | DUPLICATE_RESOURCE  |
| single currency                       | CURRENCY_MISMATCH   |

Two constraints are deliberately not translated: the uniqueness of a composition's code
and of its catalogue reference, both scoped per tenant. Those are tenancy and
catalogue-identity concerns, and the engine does not know what a tenant is.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from conftest import REFERENCE_CATEGORIES, cascade, codes, factors, line
from motor_costos import CostFactors, DiagnosticCode, ResourceLine, compute_cascade

FACTOR_NAMES = (
    "tool_wear_pct",
    "safety_equipment_pct",
    "indirect_cost_pct",
    "financing_pct",
    "utility_pct",
    "tax_pct",
)


def a_line(**overrides):
    base = {
        "resource_id": "r1",
        "category": "MAT",
        "quantity": 1,
        "unit_price": 1,
        "waste_pct": 0,
        "currency": "USD",
    }
    return ResourceLine(**{**base, **overrides})


@pytest.mark.parametrize("name", FACTOR_NAMES)
@pytest.mark.parametrize("value", ["-0.01", "100.01"])
def test_every_percentage_factor_is_bounded_to_zero_hundred(name, value):
    payload = {other: 0 for other in FACTOR_NAMES}
    payload[name] = value
    with pytest.raises(ValidationError):
        CostFactors(**payload)


@pytest.mark.parametrize("value", ["0", "100"])
def test_the_percentage_bounds_are_inclusive(value):
    payload = {other: 0 for other in FACTOR_NAMES}
    payload["tax_pct"] = value
    CostFactors(**payload)


@pytest.mark.parametrize("name", FACTOR_NAMES)
def test_no_percentage_factor_has_a_silent_default(name):
    """Defaulting all six is the tempting shortcut. An engine that defaults a tax rate
    to zero produces a number nobody chose."""
    payload = {other: 0 for other in FACTOR_NAMES if other != name}
    with pytest.raises(ValidationError):
        CostFactors(**payload)


@pytest.mark.parametrize("value", ["0", "-1"])
def test_quantity_must_be_strictly_positive(value):
    with pytest.raises(ValidationError):
        a_line(quantity=value)


def test_unit_price_may_be_zero_but_not_negative():
    a_line(unit_price="0")
    with pytest.raises(ValidationError):
        a_line(unit_price="-0.01")


@pytest.mark.parametrize("value", ["-0.01", "100.01"])
def test_waste_percentage_is_bounded(value):
    with pytest.raises(ValidationError):
        a_line(waste_pct=value)


def test_a_resource_may_appear_only_once_in_a_composition():
    result = compute_cascade(
        cascade(
            [
                line("MAT", quantity="1", unit_price="10", resource_id="cement"),
                line("MAT", quantity="2", unit_price="10", resource_id="cement"),
            ]
        )
    )
    assert not result.success
    assert DiagnosticCode.DUPLICATE_RESOURCE in codes(result)


def test_a_line_may_not_name_an_undeclared_category():
    result = compute_cascade(cascade([line("XX", quantity="1", unit_price="10")]))
    assert not result.success
    assert DiagnosticCode.UNDECLARED_CATEGORY in codes(result)


def test_the_labour_category_must_be_declared():
    result = compute_cascade(cascade([], categories=("MAT", "EQ"), labour_category="MO"))
    assert not result.success
    assert DiagnosticCode.UNDECLARED_LABOUR_CATEGORY in codes(result)


def test_declared_categories_must_be_unique():
    with pytest.raises(ValidationError):
        cascade([], categories=("MAT", "MO", "MAT"))


def test_a_float_amount_is_refused_rather_than_silently_narrowed():
    """0.1 as an IEEE double is already 0.1000000000000000055511151231257827.
    A cost engine that accepts it has lost the argument before it starts."""
    with pytest.raises(ValidationError):
        a_line(unit_price=0.1)
    with pytest.raises(ValidationError):
        CostFactors(**{name: (0.1 if name == "tax_pct" else 0) for name in FACTOR_NAMES})


def test_unknown_fields_are_refused():
    with pytest.raises(ValidationError):
        a_line(tenant_id="acme")


def test_contract_inputs_are_immutable():
    line_one = a_line()
    with pytest.raises(ValidationError):
        line_one.quantity = 5


def test_non_finite_amounts_are_refused():
    for value in ("NaN", "Infinity", "-Infinity"):
        with pytest.raises(ValidationError):
            a_line(unit_price=value)


def test_a_failed_computation_is_atomic():
    """Several invariants broken at once: still no stages, no breakdown, no unit cost."""
    result = compute_cascade(
        cascade(
            [
                line("XX", quantity="1", unit_price="10", currency="USD", resource_id="a"),
                line("MAT", quantity="1", unit_price="10", currency="PEN", resource_id="a"),
            ],
            cost_factors=factors(),
        )
    )
    assert not result.success
    assert result.stages == ()
    assert result.categories == ()
    assert result.unit_cost is None
    assert result.currency == ""
    assert set(codes(result)) >= {
        DiagnosticCode.UNDECLARED_CATEGORY,
        DiagnosticCode.DUPLICATE_RESOURCE,
        DiagnosticCode.CURRENCY_MISMATCH,
    }


def test_the_reference_taxonomy_still_computes_unchanged():
    """The parametrisation must not have cost the reference case anything."""
    result = compute_cascade(
        cascade(
            [line("MO", quantity="1", unit_price="25.00")],
            cost_factors=factors(
                tool_wear_pct="5.00",
                safety_equipment_pct="3.00",
                indirect_cost_pct="20.00",
                financing_pct="2.00",
                utility_pct="12.00",
                tax_pct="16.00",
            ),
            categories=REFERENCE_CATEGORIES,
        )
    )
    assert result.success, result.diagnostics
