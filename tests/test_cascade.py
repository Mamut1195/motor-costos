"""Known-answer tests for `cost-cascade.v1`.

The golden oracle is carried over from the implementation this engine was translated
from: the only case there that pinned a full cascade with all six factors non-zero. Its
five pinned stage values are reproduced here verbatim.

Hand-derived below, so the expected numbers can be checked without running anything:

    Input
        one MO line: quantity=1, unit_price=25.00, waste_pct=0
        tool_wear 5.00 | safety_equipment 3.00 | indirect 20.00
        financing 2.00 | utility 12.00        | tax 16.00

    Stage 0 (per line)
        partial = 1 * 25.00 * (1 + 0/100)          = 25.00

    Cascade
        total_resources = 25.00
        mo              = 25.00
        tool            = 25.00 * 5.00 / 100       = 1.25
        safety          = 25.00 * 3.00 / 100       = 0.75
        direct_cost     = 25.00 + 1.25 + 0.75      = 27.00        <- pinned
        indirect_cost   = 27.00 * 20.00 / 100      = 5.40
        subtotal_1      = 27.00 + 5.40             = 32.40        <- pinned
        financing_cost  = 32.40 * 2.00 / 100       = 0.648
        subtotal_2      = 32.40 + 0.648            = 33.048       <- pinned
        utility         = 33.048 * 12.00 / 100     = 3.96576
        subtotal_3      = 33.048 + 3.96576         = 37.01376     <- pinned
        tax             = 37.01376 * 16.00 / 100   = 5.9222016
        unit_cost       = 37.01376 + 5.9222016     = 42.9359616   <- pinned

Under the default rounding mode (`final`, scale 4) the intermediates are unchanged
and `unit_cost` quantises to 42.9360 — the value a decimal column of scale 4 stores, and
therefore the value that gets invoiced. See ADR 0001.

Note on operand order: each percentage is `base * pct / HUNDRED`, multiplying before
dividing. The engine preserves that order exactly; reversing it would change the result
whenever the division is inexact.
"""

from __future__ import annotations

from decimal import Decimal

from conftest import REFERENCE_CATEGORIES, D, by_category, by_stage, cascade, factors, line
from motor_costos import RoundingPolicy, compute_cascade

ORACLE_FACTORS = factors(
    tool_wear_pct="5.00",
    safety_equipment_pct="3.00",
    indirect_cost_pct="20.00",
    financing_pct="2.00",
    utility_pct="12.00",
    tax_pct="16.00",
)

ORACLE_STAGES = {
    "total_resources": D("25.00"),
    "tool_cost": D("1.25"),
    "safety_cost": D("0.75"),
    "direct_cost": D("27.00"),
    "indirect_cost": D("5.40"),
    "subtotal_1": D("32.40"),
    "financing_cost": D("0.648"),
    "subtotal_2": D("33.048"),
    "utility": D("3.96576"),
    "subtotal_3": D("37.01376"),
    "tax": D("5.9222016"),
}

STAGE_ORDER = (
    "total_resources",
    "tool_cost",
    "safety_cost",
    "direct_cost",
    "indirect_cost",
    "subtotal_1",
    "financing_cost",
    "subtotal_2",
    "utility",
    "subtotal_3",
    "tax",
    "unit_cost",
)


def oracle_contract(rounding: RoundingPolicy | None = None):
    return cascade(
        [line("MO", quantity="1", unit_price="25.00", waste_pct="0")],
        cost_factors=ORACLE_FACTORS,
        rounding=rounding,
    )


def test_oracle_intermediate_stages_are_exact():
    """Every intermediate reproduces the reference oracle byte for byte."""
    result = compute_cascade(oracle_contract())
    assert result.success, result.diagnostics
    stages = by_stage(result)
    for name, expected in ORACLE_STAGES.items():
        assert stages[name] == expected, name


def test_oracle_unit_cost_is_quantised_by_default():
    """Default policy is exact intermediates + final ROUND_HALF_UP at scale 4."""
    result = compute_cascade(oracle_contract())
    assert result.success, result.diagnostics
    assert result.unit_cost == Decimal("42.9360")


def test_oracle_unit_cost_is_unrounded_in_exact_mode():
    """`exact` keeps the full-precision value: seven decimals, nothing discarded."""
    result = compute_cascade(oracle_contract(RoundingPolicy(mode="exact")))
    assert result.success, result.diagnostics
    assert result.unit_cost == Decimal("42.9359616")


def test_stages_are_named_and_ordered():
    """The result identifies every stage by name, in cascade order."""
    result = compute_cascade(oracle_contract())
    assert result.success, result.diagnostics
    assert tuple(stage.name for stage in result.stages) == STAGE_ORDER


def test_partial_cost_applies_the_waste_factor():
    """Stage 0: 10 * 20 * 1.1 = 220."""
    result = compute_cascade(cascade([line("MAT", quantity="10", unit_price="20", waste_pct="10")]))
    assert result.success, result.diagnostics
    assert by_stage(result)["total_resources"] == Decimal("220")
    assert result.unit_cost == Decimal("220.0000")


def test_partial_cost_without_waste_is_quantity_times_price():
    result = compute_cascade(cascade([line("MAT", quantity="5", unit_price="30", waste_pct="0")]))
    assert result.success, result.diagnostics
    assert by_stage(result)["total_resources"] == Decimal("150")


def test_labour_surcharges_apply_to_the_declared_labour_category_only():
    """MAT=220 + MO=150: tool is 3% of 150, never of 370.

    Kills the TOOL_ON_TOTAL_NOT_MO mutant: 4.5 when the base is labour, 11.1 when it is
    the whole composition.
    """
    result = compute_cascade(
        cascade(
            [
                line("MAT", quantity="10", unit_price="20", waste_pct="10"),
                line("MO", quantity="5", unit_price="30", waste_pct="0"),
            ],
            cost_factors=factors(tool_wear_pct="3", safety_equipment_pct="2"),
        )
    )
    assert result.success, result.diagnostics
    stages = by_stage(result)
    assert stages["total_resources"] == Decimal("370")
    assert stages["tool_cost"] == Decimal("4.5")
    assert stages["safety_cost"] == Decimal("3.0")
    assert stages["direct_cost"] == Decimal("377.5")


def test_every_declared_category_is_reported_including_the_tool_category():
    """Reading back only the categories a cascade happens to name means a line in the
    unnamed one inflates direct_cost while appearing in no breakdown figure. The engine
    reports every declared category, so an unreported contributor cannot exist."""
    result = compute_cascade(
        cascade(
            [
                line("MAT", quantity="1", unit_price="100"),
                line("HE", quantity="1", unit_price="40"),
            ]
        )
    )
    assert result.success, result.diagnostics
    breakdown = by_category(result)
    assert set(breakdown) == set(REFERENCE_CATEGORIES)
    assert breakdown["HE"] == Decimal("40")
    assert breakdown["MAT"] == Decimal("100")
    assert by_stage(result)["total_resources"] == Decimal("140")


def test_category_breakdown_reconciles_with_direct_cost():
    """The invariant that a partial breakdown silently violates."""
    result = compute_cascade(
        cascade(
            [
                line("MAT", quantity="2", unit_price="50"),
                line("MO", quantity="3", unit_price="20"),
                line("HE", quantity="1", unit_price="15"),
                line("SC", quantity="1", unit_price="200"),
            ],
            cost_factors=factors(tool_wear_pct="3", safety_equipment_pct="2"),
        )
    )
    assert result.success, result.diagnostics
    stages = by_stage(result)
    total = sum(by_category(result).values(), Decimal("0"))
    assert total + stages["tool_cost"] + stages["safety_cost"] == stages["direct_cost"]


def test_stage_exponents_match_the_reference():
    """The engine keeps the reference's exponents, trailing zeros and all.

    `25.00 * 5.00` is `125.0000`; dividing by 100 preserves that scale, so the exponent
    accumulates down the chain and `subtotal_3` is `37.0137600000`, not `37.01376`. This
    is what the arithmetic produces; an oracle written with `==` never notices, because
    Decimal compares by value.

    It matters at the transport edge, where the value becomes a string. Renormalising
    would silently change what a consumer receives, so the engine does not — and this
    pins the choice rather than leaving it to be discovered.
    """
    result = compute_cascade(oracle_contract(RoundingPolicy(mode="exact")))
    assert result.success, result.diagnostics
    stages = by_stage(result)
    assert str(stages["subtotal_3"]) == "37.0137600000"
    assert stages["subtotal_3"] == Decimal("37.01376")
    assert str(result.unit_cost) == "42.935961600000"
    assert result.unit_cost == Decimal("42.9359616")


def test_quantised_modes_produce_a_clean_representation():
    """Whatever the intermediates look like, the quantised unit cost is exact-width."""
    for mode in ("final", "per-stage"):
        result = compute_cascade(oracle_contract(RoundingPolicy(mode=mode)))
        assert str(result.unit_cost) == "42.9360", mode


def test_empty_composition_is_zero_not_an_error():
    result = compute_cascade(cascade([]))
    assert result.success, result.diagnostics
    assert result.unit_cost == Decimal("0.0000")
    assert by_stage(result)["total_resources"] == Decimal("0")
