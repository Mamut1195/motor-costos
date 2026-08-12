"""`cost-cascade.v1` — the unit-price cascade over an APU composition.

Translated from a prior in-house implementation: the stages and their bases are its
domain knowledge, while the ORM coupling, the fixed category enum and the implicit
rounding it relied on are deliberately absent here.

Operand order is load-bearing. Each percentage is `base * pct / HUNDRED` — multiply, then
divide. Reversing it to `base * (pct / HUNDRED)` changes the result whenever the division
is inexact, so this module preserves the order exactly.

Stage 0 lives here too. Where the per-line total is computed outside the cascade, the
cascade never sees a quantity, a price or a waste percentage — and a caller that hands in
a pre-computed line total is a caller that can apply the waste factor twice. An engine
taking those three as input owns that stage.
"""

from __future__ import annotations

from decimal import Decimal

from motor_costos.contracts import (
    MAX_CATEGORIES,
    MAX_NESTING_DEPTH,
    MAX_RESOURCE_LINES,
    CostCascadeV1,
)
from motor_costos.diagnostics import Diagnostic, DiagnosticCode, cap, error
from motor_costos.models import CategoryCost, CostCascadeResult, CostStage
from motor_costos.rounding import Rounder, engine_context

ZERO = Decimal("0")
ONE = Decimal("1")
HUNDRED = Decimal("100")

#: Integer digits a monetary value may carry. The domain stores money as
#: a decimal of precision 14 and scale 4, leaving ten digits before the point. Exceeding
#: it fails the whole computation here rather than raising a database exception later --
#: the failure mode an engine-less implementation leaves open.
MAX_MONEY_INTEGER_DIGITS = 10

#: Diagnostics in one result, capped with an announcement of the truncation.
MAX_DIAGNOSTICS = 1_000

_MONEY_CEILING = Decimal(10) ** MAX_MONEY_INTEGER_DIGITS
_STAGE = "cost-cascade.v1"

#: Stage names, in cascade order. Part of the contract.
STAGE_NAMES = (
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


def _failed(diagnostics: tuple[Diagnostic, ...]) -> CostCascadeResult:
    """A failed cascade carries no stages, no breakdown and no unit cost.

    Never a partial result that looks complete.
    """
    return CostCascadeResult(success=False, diagnostics=cap(diagnostics, MAX_DIAGNOSTICS, _STAGE))


def _over_ceiling(value: Decimal) -> bool:
    return value.copy_abs() >= _MONEY_CEILING


def _validate(contract: CostCascadeV1) -> tuple[Diagnostic, ...]:
    diagnostics: list[Diagnostic] = []
    declared = set(contract.categories)

    if len(contract.categories) > MAX_CATEGORIES:
        diagnostics.append(
            error(
                DiagnosticCode.LIMIT_CATEGORIES,
                _STAGE,
                "Declared category count exceeds the limit.",
                "Split the taxonomy or raise the limit deliberately.",
                observed=len(contract.categories),
                limit=MAX_CATEGORIES,
            )
        )

    if len(contract.lines) > MAX_RESOURCE_LINES:
        diagnostics.append(
            error(
                DiagnosticCode.LIMIT_RESOURCE_LINES,
                _STAGE,
                "Resource line count exceeds the limit.",
                "Split the composition or raise the limit deliberately.",
                observed=len(contract.lines),
                limit=MAX_RESOURCE_LINES,
            )
        )

    if contract.labour_category not in declared:
        diagnostics.append(
            error(
                DiagnosticCode.UNDECLARED_LABOUR_CATEGORY,
                _STAGE,
                "The labour category is not one of the declared categories.",
                "Declare the labour category in `categories`.",
                labour_category=contract.labour_category,
            )
        )

    seen: set[str] = set()
    for index, line in enumerate(contract.lines):
        pointer = f"/lines/{index}"
        if line.category not in declared:
            diagnostics.append(
                error(
                    DiagnosticCode.UNDECLARED_CATEGORY,
                    _STAGE,
                    "A line names a category that was not declared.",
                    "Declare the category in `categories` or correct the line.",
                    json_pointer=pointer,
                    resource_id=line.resource_id,
                    category=line.category,
                )
            )
        if line.resource_id in seen:
            diagnostics.append(
                error(
                    DiagnosticCode.DUPLICATE_RESOURCE,
                    _STAGE,
                    "A resource appears more than once in the composition.",
                    "Merge the duplicate lines into one with the combined quantity.",
                    json_pointer=pointer,
                    resource_id=line.resource_id,
                )
            )
        seen.add(line.resource_id)
        if _over_ceiling(line.unit_price):
            diagnostics.append(
                error(
                    DiagnosticCode.LIMIT_MONEY_MAGNITUDE,
                    _STAGE,
                    "A unit price exceeds the representable monetary magnitude.",
                    "Check the price, or the currency it is expressed in.",
                    json_pointer=pointer,
                    resource_id=line.resource_id,
                    limit_integer_digits=MAX_MONEY_INTEGER_DIGITS,
                )
            )

    return tuple(diagnostics)


def _single_currency(contract: CostCascadeV1) -> tuple[str, Diagnostic | None]:
    """The one currency of the composition, or a diagnostic.

    Folded with `strip().upper()`. Reporting two of the currencies as `expected` and
    `found` -- as an implementation that sorts them and takes the first two does --
    asserts a precedence that does not exist and hides the third. This reports the
    complete sorted set and claims nothing about which one governs.
    """
    currencies = sorted({line.currency.strip().upper() for line in contract.lines})
    if len(currencies) > 1:
        return "", error(
            DiagnosticCode.CURRENCY_MISMATCH,
            _STAGE,
            "The composition mixes currencies and the engine converts none.",
            "Express every line in one currency before computing.",
            currencies=",".join(currencies),
        )
    return (currencies[0] if currencies else ""), None


def compute_cascade(contract: CostCascadeV1) -> CostCascadeResult:
    """Compute the full cost breakdown of a composition. Never raises."""
    with engine_context():
        return _compute(contract)


def _compute(contract: CostCascadeV1) -> CostCascadeResult:
    diagnostics = _validate(contract)

    # Single-currency invariant: reject BEFORE summing any cost.
    currency, mismatch = _single_currency(contract)
    if mismatch is not None:
        diagnostics = (*diagnostics, mismatch)

    if diagnostics:
        return _failed(diagnostics)

    rounder = Rounder(contract.rounding)

    # Stage 0, per line. In `per-stage` mode the line total is quantised here, so the
    # per-category figures and their sum stay exactly reconcilable.
    #
    # The ceiling is checked between the arithmetic and the quantisation, and that order
    # is the whole point. `quantity` carries no upper bound of its own -- an APU asking
    # for 1e30 of something is a composition error, not a representable number -- so
    # without this check `rounder.stage` reaches `Decimal.quantize` with a value needing
    # more than ENGINE_PRECISION digits and raises `InvalidOperation` out of a function
    # documented never to raise.
    #
    # Bounding the line total is also what keeps every later stage quantisable, and the
    # headroom is not incidental. At most MAX_RESOURCE_LINES lines, each under the money
    # ceiling, bound the resource total; tool and safety are each at most the labour
    # total, so direct cost is at most three times it; four percentages of at most 100%
    # then compound, multiplying by at most sixteen. Forty-eight times the resource
    # total, plus the largest money_scale a caller may request, still fits inside
    # ENGINE_PRECISION. `test_the_line_ceiling_leaves_headroom_for_every_stage` asserts
    # that arithmetic, so raising any of those limits fails the suite, not production.
    overflows: list[Diagnostic] = []
    by_category: dict[str, Decimal] = {category: ZERO for category in contract.categories}
    for index, line in enumerate(contract.lines):
        waste_factor = ONE + line.waste_pct / HUNDRED
        partial = line.quantity * line.unit_price * waste_factor
        if _over_ceiling(partial):
            overflows.append(
                error(
                    DiagnosticCode.LIMIT_MONEY_MAGNITUDE,
                    _STAGE,
                    "A line total exceeds the representable monetary magnitude.",
                    "Check the quantity, the price, or the currency they are expressed in.",
                    json_pointer=f"/lines/{index}",
                    resource_id=line.resource_id,
                    limit_integer_digits=MAX_MONEY_INTEGER_DIGITS,
                )
            )
            continue
        by_category[line.category] += rounder.stage(partial)

    if overflows:
        return _failed(tuple(overflows))

    total_resources = rounder.stage(sum(by_category.values(), ZERO))
    labour = by_category[contract.labour_category]

    f = contract.factors
    tool = rounder.stage(labour * f.tool_wear_pct / HUNDRED)
    safety = rounder.stage(labour * f.safety_equipment_pct / HUNDRED)

    direct_cost = rounder.stage(total_resources + tool + safety)
    indirect_cost = rounder.stage(direct_cost * f.indirect_cost_pct / HUNDRED)
    subtotal_1 = rounder.stage(direct_cost + indirect_cost)
    financing_cost = rounder.stage(subtotal_1 * f.financing_pct / HUNDRED)
    subtotal_2 = rounder.stage(subtotal_1 + financing_cost)
    utility = rounder.stage(subtotal_2 * f.utility_pct / HUNDRED)
    subtotal_3 = rounder.stage(subtotal_2 + utility)
    tax = rounder.stage(subtotal_3 * f.tax_pct / HUNDRED)
    unit_cost = rounder.final(subtotal_3 + tax)

    amounts = (
        total_resources,
        tool,
        safety,
        direct_cost,
        indirect_cost,
        subtotal_1,
        financing_cost,
        subtotal_2,
        utility,
        subtotal_3,
        tax,
        unit_cost,
    )

    for name, amount in zip(STAGE_NAMES, amounts, strict=True):
        if _over_ceiling(amount):
            return _failed(
                (
                    error(
                        DiagnosticCode.LIMIT_MONEY_MAGNITUDE,
                        _STAGE,
                        "A cascade stage exceeds the representable monetary magnitude.",
                        "Reduce the composition or check the factors and prices.",
                        cascade_stage=name,
                        limit_integer_digits=MAX_MONEY_INTEGER_DIGITS,
                    ),
                )
            )

    # Reconciliation invariant. The reference cannot satisfy this whenever a line carries
    # the tool category: its breakdown sums six categories and reports five, so a real
    # cost silently has no line in the answer. Reporting every declared category makes an
    # unreported contributor structurally impossible; this asserts it.
    if sum(by_category.values(), ZERO) + tool + safety != direct_cost:
        return _failed(
            (
                error(
                    DiagnosticCode.RECONCILIATION_FAILED,
                    _STAGE,
                    "The category breakdown does not reconcile with the direct cost.",
                    "Report this: it is an engine defect, not a composition error.",
                ),
            )
        )

    return CostCascadeResult(
        success=True,
        currency=currency,
        categories=tuple(
            CategoryCost(category=category, cost=by_category[category])
            for category in contract.categories
        ),
        stages=tuple(
            CostStage(name=name, amount=amount)
            for name, amount in zip(STAGE_NAMES, amounts, strict=True)
        ),
        unit_cost=unit_cost,
        rounding=contract.rounding,
    )


__all__ = [
    "MAX_DIAGNOSTICS",
    "MAX_MONEY_INTEGER_DIGITS",
    "MAX_NESTING_DEPTH",
    "STAGE_NAMES",
    "compute_cascade",
]
