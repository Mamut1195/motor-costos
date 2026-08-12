"""Mutation testing against the real engine source.

A test that cannot fail for the reason it states is not a test. This module breaks one
step of the cascade at a time and requires that a **named** test fails because of it.
If a mutant survives, the test that claims to cover that step is decoration.

Why the source and not a mirror: the common pattern is to keep a hand-written copy of
the formula, mutate the copy, and assert `mutated != correct`. That shows the mutant
changes the number; it does not show that any real test would notice, and the inference
from "the number changes" to "an oracle fails" stays unautomated. Here the mutation is
applied to the bytes of `cascade.py` and `rounding.py`, and the assertion is that a
specific named test raises.

Anchor safety: `build_engine` refuses to run unless the anchor text occurs exactly once
in the real source. That check happens outside the `pytest.raises` block on purpose — a
missing anchor after a refactor must break this suite loudly, not be mistaken for a
caught mutant.
"""

from __future__ import annotations

from pathlib import Path
from types import ModuleType

import pytest

import test_cascade
import test_rounding

SRC = Path(__file__).resolve().parent.parent / "src" / "motor_costos"
CASCADE_SOURCE = SRC / "cascade.py"
ROUNDING_SOURCE = SRC / "rounding.py"


def _load(name: str, path: Path, substitution: tuple[str, str] | None) -> ModuleType:
    source = path.read_text(encoding="utf-8")
    if substitution is not None:
        old, new = substitution
        found = source.count(old)
        if found != 1:
            raise AssertionError(
                f"mutation anchor occurs {found} times in {path.name}, expected exactly 1: {old!r}"
            )
        source = source.replace(old, new)
    module = ModuleType(f"motor_costos._mutant_{name}")
    module.__file__ = str(path)
    exec(compile(source, str(path), "exec"), module.__dict__)  # noqa: S102
    return module


def build_engine(
    cascade_sub: tuple[str, str] | None = None,
    rounding_sub: tuple[str, str] | None = None,
):
    """A `compute_cascade` built from the real source with at most one line changed."""
    rounding = _load("rounding", ROUNDING_SOURCE, rounding_sub)
    cascade = _load("cascade", CASCADE_SOURCE, cascade_sub)
    # cascade.py resolves these as globals at call time, so swapping them here is enough
    # to make a rounding mutation visible through the cascade.
    cascade.Rounder = rounding.Rounder
    cascade.engine_context = rounding.engine_context
    return cascade.compute_cascade


def run_named_test(module: ModuleType, test_name: str, engine) -> None:
    original = module.compute_cascade
    module.compute_cascade = engine
    try:
        getattr(module, test_name)()
    finally:
        module.compute_cascade = original


# (mutant, file, anchor, replacement, test module, test that must fail)
MUTANTS = [
    (
        "PARTIAL_COST_DROP_WASTE",
        "cascade",
        "partial = rounder.stage(line.quantity * line.unit_price * waste_factor)",
        "partial = rounder.stage(line.quantity * line.unit_price)",
        test_cascade,
        "test_partial_cost_applies_the_waste_factor",
    ),
    (
        "PARTIAL_COST_MULTIPLY_WASTE",
        "cascade",
        "partial = rounder.stage(line.quantity * line.unit_price * waste_factor)",
        "partial = rounder.stage(line.quantity * line.unit_price * (line.waste_pct / HUNDRED))",
        test_cascade,
        "test_partial_cost_applies_the_waste_factor",
    ),
    (
        "TOOL_ON_TOTAL_NOT_MO",
        "cascade",
        "tool = rounder.stage(labour * f.tool_wear_pct / HUNDRED)",
        "tool = rounder.stage(total_resources * f.tool_wear_pct / HUNDRED)",
        test_cascade,
        "test_labour_surcharges_apply_to_the_declared_labour_category_only",
    ),
    (
        "SAFETY_ON_TOTAL_NOT_MO",
        "cascade",
        "safety = rounder.stage(labour * f.safety_equipment_pct / HUNDRED)",
        "safety = rounder.stage(total_resources * f.safety_equipment_pct / HUNDRED)",
        test_cascade,
        "test_labour_surcharges_apply_to_the_declared_labour_category_only",
    ),
    (
        "SWAP_DIRECT_COST_SIGN",
        "cascade",
        "direct_cost = rounder.stage(total_resources + tool + safety)",
        "direct_cost = rounder.stage(total_resources - tool + safety)",
        test_cascade,
        "test_oracle_intermediate_stages_are_exact",
    ),
    (
        "DROP_INDIRECT_FACTOR",
        "cascade",
        "indirect_cost = rounder.stage(direct_cost * f.indirect_cost_pct / HUNDRED)",
        "indirect_cost = ZERO",
        test_cascade,
        "test_oracle_intermediate_stages_are_exact",
    ),
    (
        "SWAP_SUBTOTAL1_SIGN",
        "cascade",
        "subtotal_1 = rounder.stage(direct_cost + indirect_cost)",
        "subtotal_1 = rounder.stage(direct_cost - indirect_cost)",
        test_cascade,
        "test_oracle_intermediate_stages_are_exact",
    ),
    (
        "FINANCING_BASE_IS_CD",
        "cascade",
        "financing_cost = rounder.stage(subtotal_1 * f.financing_pct / HUNDRED)",
        "financing_cost = rounder.stage(direct_cost * f.financing_pct / HUNDRED)",
        test_cascade,
        "test_oracle_intermediate_stages_are_exact",
    ),
    (
        "FINANCING_SIGN",
        "cascade",
        "subtotal_2 = rounder.stage(subtotal_1 + financing_cost)",
        "subtotal_2 = rounder.stage(subtotal_1 - financing_cost)",
        test_cascade,
        "test_oracle_intermediate_stages_are_exact",
    ),
    (
        "UTILITY_BASE_IS_S1",
        "cascade",
        "utility = rounder.stage(subtotal_2 * f.utility_pct / HUNDRED)",
        "utility = rounder.stage(subtotal_1 * f.utility_pct / HUNDRED)",
        test_cascade,
        "test_oracle_intermediate_stages_are_exact",
    ),
    (
        "REORDER_TAX_BEFORE_UTILITY",
        "cascade",
        "tax = rounder.stage(subtotal_3 * f.tax_pct / HUNDRED)",
        "tax = rounder.stage(subtotal_2 * f.tax_pct / HUNDRED)",
        test_cascade,
        "test_oracle_intermediate_stages_are_exact",
    ),
    (
        "DROP_TOOL_FROM_DIRECT_COST",
        "cascade",
        "direct_cost = rounder.stage(total_resources + tool + safety)",
        "direct_cost = rounder.stage(total_resources + safety)",
        test_cascade,
        "test_category_breakdown_reconciles_with_direct_cost",
    ),
    (
        "TOOL_CATEGORY_DROPPED_FROM_BREAKDOWN",
        "cascade",
        "by_category[line.category] += partial",
        "by_category[line.category] += partial if line.category != 'HE' else ZERO",
        test_cascade,
        "test_every_declared_category_is_reported_including_the_tool_category",
    ),
    (
        "ROUNDING_IS_BANKERS_NOT_HALF_UP",
        "rounding",
        "return value.quantize(self._exponent, rounding=ROUND_HALF_UP)",
        "return value.quantize(self._exponent, rounding=decimal.ROUND_HALF_EVEN)",
        test_rounding,
        "test_half_up_fires_at_the_exact_boundary",
    ),
    (
        "FINAL_MODE_DOES_NOT_QUANTISE",
        "rounding",
        'self._quantise_final = policy.mode in ("final", "per-stage")',
        'self._quantise_final = policy.mode == "per-stage"',
        test_cascade,
        "test_oracle_unit_cost_is_quantised_by_default",
    ),
    (
        "PER_STAGE_MODE_IS_A_NO_OP",
        "rounding",
        'self._per_stage = policy.mode == "per-stage"',
        "self._per_stage = False",
        test_rounding,
        "test_per_stage_mode_quantises_every_stage",
    ),
    (
        "DECIMAL_CONTEXT_NOT_ISOLATED",
        "rounding",
        "ctx.prec = ENGINE_PRECISION",
        "ctx.prec = ctx.prec",
        test_rounding,
        "test_result_is_independent_of_the_callers_decimal_context",
    ),
]


@pytest.mark.parametrize(
    ("source", "anchor", "replacement", "module", "test_name"),
    [(m[1], m[2], m[3], m[4], m[5]) for m in MUTANTS],
    ids=[m[0] for m in MUTANTS],
)
def test_mutant_is_killed_by_a_named_test(source, anchor, replacement, module, test_name):
    """Break one step of the real cascade; the test that covers it must fail."""
    substitution = (anchor, replacement)
    engine = build_engine(
        cascade_sub=substitution if source == "cascade" else None,
        rounding_sub=substitution if source == "rounding" else None,
    )
    with pytest.raises(AssertionError):
        run_named_test(module, test_name, engine)


@pytest.mark.parametrize("test_name", sorted({m[5] for m in MUTANTS}))
def test_the_harness_passes_on_the_unmutated_engine(test_name):
    """Control: without a mutation every named test passes, so the kills above mean
    something. Without this, a harness that broke everything would look perfect."""
    engine = build_engine()
    module = next(m[4] for m in MUTANTS if m[5] == test_name)
    run_named_test(module, test_name, engine)


def test_every_anchor_occurs_exactly_once_in_the_real_source():
    """A refactor that moves an anchor must break this suite loudly rather than
    silently turning its mutants into no-ops."""
    sources = {
        "cascade": CASCADE_SOURCE.read_text(encoding="utf-8"),
        "rounding": ROUNDING_SOURCE.read_text(encoding="utf-8"),
    }
    for name, source, anchor, _replacement, _module, _test in MUTANTS:
        assert sources[source].count(anchor) == 1, name


def test_the_mutant_count_is_pinned():
    """The README states this number; nothing else would stop it drifting."""
    assert len(MUTANTS) == 17
    assert len({m[0] for m in MUTANTS}) == 17, "mutant names must be unique"
