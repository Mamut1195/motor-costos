"""The rounding policy: three modes, half-up ties, and no dependence on the caller's context.

The half-up boundary cases are ported from the implementation this engine was
translated from, which pins ROUND_HALF_UP with ties that banker's rounding would resolve
the other way. There the policy applied to presentation only; here it is a contract
input. See ADR 0001.
"""

from __future__ import annotations

import decimal
from decimal import Decimal

from conftest import by_stage, cascade, factors, line

from motor_costos import RoundingPolicy, compute_cascade

ORACLE_FACTORS = factors(
    tool_wear_pct="5.00",
    safety_equipment_pct="3.00",
    indirect_cost_pct="20.00",
    financing_pct="2.00",
    utility_pct="12.00",
    tax_pct="16.00",
)


def priced(amount: str, scale: int = 2):
    """A one-line composition with no factors, so unit_cost == amount exactly."""
    return cascade(
        [line("MAT", quantity="1", unit_price=amount)],
        rounding=RoundingPolicy(mode="final", money_scale=scale),
    )


def oracle(mode: str):
    return cascade(
        [line("MO", quantity="1", unit_price="25.00")],
        cost_factors=ORACLE_FACTORS,
        rounding=RoundingPolicy(mode=mode),
    )


def test_half_up_fires_at_the_exact_boundary():
    """0.005 -> 0.01. Banker's rounding would give 0.00 (zero is even)."""
    result = compute_cascade(priced("0.005"))
    assert result.success, result.diagnostics
    assert result.unit_cost == Decimal("0.01")


def test_just_below_the_boundary_rounds_down():
    result = compute_cascade(priced("0.004999"))
    assert result.success, result.diagnostics
    assert result.unit_cost == Decimal("0.00")


def test_half_up_at_the_next_centesimal_boundary():
    result = compute_cascade(priced("0.015"))
    assert result.success, result.diagnostics
    assert result.unit_cost == Decimal("0.02")


def test_just_below_the_next_boundary_rounds_down():
    result = compute_cascade(priced("0.014999"))
    assert result.success, result.diagnostics
    assert result.unit_cost == Decimal("0.01")


def test_large_value_half_up_is_not_bankers():
    """1234.565 -> 1234.57 via ROUND_HALF_UP, not banker's 1234.56."""
    result = compute_cascade(priced("1234.565"))
    assert result.success, result.diagnostics
    assert result.unit_cost == Decimal("1234.57")


def test_half_up_ties_at_the_money_scale_of_four():
    """Ties at scale 4 that banker's rounding would resolve downwards."""
    assert compute_cascade(priced("0.00005", scale=4)).unit_cost == Decimal("0.0001")
    assert compute_cascade(priced("0.00025", scale=4)).unit_cost == Decimal("0.0003")


def test_exact_mode_never_quantises():
    result = compute_cascade(oracle("exact"))
    assert result.success, result.diagnostics
    assert result.unit_cost == Decimal("42.9359616")
    assert by_stage(result)["subtotal_3"] == Decimal("37.01376")


def test_final_mode_keeps_intermediates_exact():
    result = compute_cascade(oracle("final"))
    assert result.success, result.diagnostics
    assert by_stage(result)["subtotal_3"] == Decimal("37.01376")
    assert result.unit_cost == Decimal("42.9360")


def test_per_stage_mode_quantises_every_stage():
    """Distinguished from `final` at subtotal_3: 37.0138 rather than 37.01376.

    Hand-derived at scale 4:
        utility    = 33.0480 * 12/100 = 3.96576  -> 3.9658
        subtotal_3 = 33.0480 + 3.9658           = 37.0138
        tax        = 37.0138 * 16/100 = 5.922208 -> 5.9222
        unit_cost  = 37.0138 + 5.9222           = 42.9360
    """
    result = compute_cascade(oracle("per-stage"))
    assert result.success, result.diagnostics
    stages = by_stage(result)
    assert stages["utility"] == Decimal("3.9658")
    assert stages["subtotal_3"] == Decimal("37.0138")
    assert result.unit_cost == Decimal("42.9360")


def test_the_three_modes_disagree_on_subtotal_3():
    """If they agreed, the mode would not be a decision worth putting in the contract."""
    exact = by_stage(compute_cascade(oracle("exact")))["subtotal_3"]
    final = by_stage(compute_cascade(oracle("final")))["subtotal_3"]
    per_stage = by_stage(compute_cascade(oracle("per-stage")))["subtotal_3"]
    assert exact == final == Decimal("37.01376")
    assert per_stage == Decimal("37.0138")
    assert per_stage != exact


def test_result_is_independent_of_the_callers_decimal_context():
    """A caller lowering `prec` must not be able to move the answer.

    Inheriting the ambient decimal context is the usual omission, and it quietly makes a
    determinism promise false."""
    baseline = compute_cascade(oracle("exact")).unit_cost
    original = decimal.getcontext().prec
    try:
        decimal.getcontext().prec = 6
        assert compute_cascade(oracle("exact")).unit_cost == baseline
    finally:
        decimal.getcontext().prec = original


def test_the_default_policy_is_pinned():
    """Guards the default against a silent change; the monkeypatched tests cannot see it."""
    policy = RoundingPolicy()
    assert policy.mode == "final"
    assert policy.money_scale == 4
