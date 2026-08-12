"""Public motor-costos API."""

from motor_costos._version import __version__
from motor_costos.cascade import (
    MAX_MONEY_INTEGER_DIGITS,
    MAX_NESTING_DEPTH,
    compute_cascade,
)
from motor_costos.contracts import (
    CONTRACTS,
    MAX_CATEGORIES,
    MAX_RESOURCE_LINES,
    CostCascadeV1,
    DimensionCheckV1,
)
from motor_costos.diagnostics import Diagnostic, DiagnosticCode
from motor_costos.dimensions import (
    QUANTITY_FIELDS,
    SATISFIABLE_UNIT_CATEGORIES,
    UNIT_CATEGORIES,
    check_dimension,
)
from motor_costos.models import (
    Capabilities,
    CategoryCost,
    CostCascadeResult,
    CostFactors,
    CostStage,
    DimensionCheckResult,
    ResourceLine,
    RoundingPolicy,
)
from motor_costos.rounding import ENGINE_PRECISION, ROUNDING_MODES

__all__ = [
    "MAX_MONEY_INTEGER_DIGITS",
    "Capabilities",
    "CategoryCost",
    "CostCascadeResult",
    "CostCascadeV1",
    "CostFactors",
    "CostStage",
    "Diagnostic",
    "DiagnosticCode",
    "DimensionCheckResult",
    "DimensionCheckV1",
    "ResourceLine",
    "RoundingPolicy",
    "__version__",
    "capabilities",
    "check_dimension",
    "compute_cascade",
]


def capabilities() -> Capabilities:
    """Declare what this build supports.

    `contract_versions` is derived from the contract registry, not restated, so a new
    contract cannot ship without appearing here.
    """
    default = RoundingPolicy()
    return Capabilities(
        version=__version__,
        contract_versions=tuple(CONTRACTS),
        rounding_modes=ROUNDING_MODES,
        default_rounding_mode=default.mode,
        default_money_scale=default.money_scale,
        engine_precision=ENGINE_PRECISION,
        quantity_fields=QUANTITY_FIELDS,
        satisfiable_unit_categories=SATISFIABLE_UNIT_CATEGORIES,
        unit_categories=UNIT_CATEGORIES,
        max_resource_lines=MAX_RESOURCE_LINES,
        max_categories=MAX_CATEGORIES,
        max_nesting_depth=MAX_NESTING_DEPTH,
    )
