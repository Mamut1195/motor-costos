"""Fixed limits, verified at their exact boundary.

Each limit is tested one below and one above by lowering the constant with monkeypatch,
plus a separate test that pins the real shipped value — otherwise a monkeypatched
boundary test would keep passing after someone changed the default.

A limit exceeded fails the whole computation. Never a partial result that looks complete.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from conftest import cascade, codes, factors, line
from motor_costos import DiagnosticCode, ResourceLine, RoundingPolicy, compute_cascade
from motor_costos import cascade as cascade_module
from motor_costos.models import MAX_ID_LENGTH, MAX_MONEY_SCALE
from motor_costos.rounding import ENGINE_PRECISION


def lines(count: int):
    return [
        line("MAT", quantity="1", unit_price="1", resource_id=f"r{index}")
        for index in range(count)
    ]


@pytest.mark.parametrize(("budget", "ok"), [(4, True), (3, False)])
def test_resource_line_count_exact_boundary(monkeypatch, budget, ok):
    monkeypatch.setattr(cascade_module, "MAX_RESOURCE_LINES", budget)
    result = compute_cascade(cascade(lines(4)))
    assert result.success is ok
    if not ok:
        assert DiagnosticCode.LIMIT_RESOURCE_LINES in codes(result)
        assert result.stages == ()
        assert result.unit_cost is None


@pytest.mark.parametrize(("budget", "ok"), [(3, True), (2, False)])
def test_declared_category_count_exact_boundary(monkeypatch, budget, ok):
    monkeypatch.setattr(cascade_module, "MAX_CATEGORIES", budget)
    result = compute_cascade(cascade([], categories=("MAT", "MO", "EQ")))
    assert result.success is ok
    if not ok:
        assert DiagnosticCode.LIMIT_CATEGORIES in codes(result)


def test_unit_price_at_the_magnitude_ceiling_is_accepted():
    """Ten integer digits is the most a DecimalField(14, 4) can hold."""
    result = compute_cascade(cascade([line("MAT", quantity="1", unit_price="9999999999")]))
    assert result.success, result.diagnostics


def test_unit_price_above_the_magnitude_ceiling_is_rejected():
    result = compute_cascade(cascade([line("MAT", quantity="1", unit_price="10000000000")]))
    assert not result.success
    assert DiagnosticCode.LIMIT_MONEY_MAGNITUDE in codes(result)
    assert result.stages == ()


def test_a_line_total_over_the_ceiling_names_the_line():
    """Both inputs are individually representable; their product is not.

    This is the failure the reference leaves open: it would hand the oversized Decimal
    to the database and raise there instead of rounding or refusing here.

    The diagnostic names the offending line rather than a cascade stage, because the
    line is where a caller can act. A ceiling enforced only downstream would still
    refuse this composition, but it would point at `total_resources` and leave the
    caller to find which of ten thousand lines produced it.
    """
    result = compute_cascade(cascade([line("MAT", quantity="1000000", unit_price="1000000")]))
    assert not result.success
    assert DiagnosticCode.LIMIT_MONEY_MAGNITUDE in codes(result)
    assert result.stages == ()
    assert result.categories == ()
    assert result.unit_cost is None

    overflow = next(d for d in result.diagnostics if d.code == DiagnosticCode.LIMIT_MONEY_MAGNITUDE)
    assert overflow.json_pointer == "/lines/0"
    assert overflow.resource_id == "MAT-1000000-1000000-0"


def test_every_offending_line_is_reported_not_just_the_first():
    """Line-level refusals batch, exactly as undeclared categories and duplicates do."""
    offenders = [
        line("MAT", quantity="1000000", unit_price="1000000", resource_id=f"r{index}")
        for index in range(3)
    ]
    result = compute_cascade(cascade([*offenders, line("MAT", quantity="1", unit_price="1")]))
    assert not result.success
    pointers = [d.json_pointer for d in result.diagnostics]
    assert pointers == ["/lines/0", "/lines/1", "/lines/2"]


@pytest.mark.parametrize("quantity", ["1e30", "1e60"])
@pytest.mark.parametrize("mode", ["exact", "final", "per-stage"])
@pytest.mark.parametrize("money_scale", [0, MAX_MONEY_SCALE])
def test_the_engine_never_raises_on_an_unbounded_quantity(quantity, mode, money_scale):
    """The promise, exercised where it used to break.

    `quantity` carries no upper bound of its own, so a composition can ask for a number
    that no `money_scale` can quantise. Quantising it raised `decimal.InvalidOperation`
    out of a function documented never to raise -- and over the sidecar that became an
    `Internal error` where a typed refusal belongs.
    """
    result = compute_cascade(
        cascade(
            [line("MAT", quantity=quantity, unit_price="1")],
            rounding=RoundingPolicy(mode=mode, money_scale=money_scale),
        )
    )
    assert not result.success
    assert DiagnosticCode.LIMIT_MONEY_MAGNITUDE in codes(result)
    assert result.unit_cost is None


def test_the_line_ceiling_leaves_headroom_for_every_stage():
    """The bound argument, executable rather than asserted in a comment.

    Bounding each line total is what makes every later stage quantisable. The worst
    case: `MAX_RESOURCE_LINES` lines at the ceiling, tool and safety each at most the
    labour total, then four percentages of at most 100% compounding on top -- so at
    most 3 * 16 = 48 times the resource total. That figure, plus the largest scale a
    caller may request, must still fit inside `ENGINE_PRECISION`.

    Raising `MAX_RESOURCE_LINES`, `MAX_MONEY_INTEGER_DIGITS` or `MAX_MONEY_SCALE`
    without redoing this arithmetic fails here instead of raising in production.
    """
    ceiling = Decimal(10) ** cascade_module.MAX_MONEY_INTEGER_DIGITS
    worst_unit_cost = ceiling * cascade_module.MAX_RESOURCE_LINES * 48
    integer_digits = len(worst_unit_cost.to_integral_value().as_tuple().digits)
    assert integer_digits + MAX_MONEY_SCALE <= ENGINE_PRECISION


def test_a_stage_overflow_names_the_stage():
    result = compute_cascade(
        cascade(
            [line("MAT", quantity="1", unit_price="9999999999")],
            cost_factors=factors(utility_pct="100", tax_pct="100"),
        )
    )
    assert not result.success
    overflow = next(d for d in result.diagnostics if d.code == DiagnosticCode.LIMIT_MONEY_MAGNITUDE)
    assert any(entry.startswith("cascade_stage=") for entry in overflow.context)


@pytest.mark.parametrize(("budget", "expected"), [(3, 3), (2, 2)])
def test_diagnostics_are_capped_and_the_cap_announces_itself(monkeypatch, budget, expected):
    monkeypatch.setattr(cascade_module, "MAX_DIAGNOSTICS", budget)
    offenders = [
        line("NOPE", quantity="1", unit_price="1", resource_id=f"r{index}") for index in range(10)
    ]
    result = compute_cascade(cascade(offenders))
    assert not result.success
    assert len(result.diagnostics) == expected
    assert result.diagnostics[-1].code == DiagnosticCode.LIMIT_DIAGNOSTICS
    assert any(entry.startswith("dropped=") for entry in result.diagnostics[-1].context)


def test_identifier_at_the_length_boundary_is_accepted():
    ResourceLine(
        resource_id="r" * MAX_ID_LENGTH,
        category="MAT",
        quantity=1,
        unit_price=1,
        waste_pct=0,
        currency="USD",
    )


def test_identifier_above_the_length_boundary_is_rejected():
    with pytest.raises(ValidationError):
        ResourceLine(
            resource_id="r" * (MAX_ID_LENGTH + 1),
            category="MAT",
            quantity=1,
            unit_price=1,
            waste_pct=0,
            currency="USD",
        )


def test_the_shipped_limits_are_pinned():
    """Guards the defaults against the monkeypatched tests above hiding a change."""
    assert cascade_module.MAX_RESOURCE_LINES == 10_000
    assert cascade_module.MAX_CATEGORIES == 64
    assert cascade_module.MAX_DIAGNOSTICS == 1_000
    assert cascade_module.MAX_MONEY_INTEGER_DIGITS == 10
    assert cascade_module.MAX_NESTING_DEPTH == 1
    assert MAX_ID_LENGTH == 100
    assert MAX_MONEY_SCALE == 10
