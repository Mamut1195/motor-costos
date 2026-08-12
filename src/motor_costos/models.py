"""Domain and result types.

Every model is frozen, forbids unknown fields, and rejects non-finite values. Decimal
fields additionally reject `float` inputs: a monetary value that arrives as an IEEE
double has already lost precision before the engine sees it, and a cost engine must
not accept that silently. Amounts are given as a string or an integer.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated, Any, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, WithJsonSchema

from motor_costos.diagnostics import Diagnostic

#: Ceiling on any caller-supplied identifier (resource id, category, currency).
MAX_ID_LENGTH = 100

#: Largest `money_scale` a caller may request.
MAX_MONEY_SCALE = 10


class FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


def _reject_float(value: Any) -> Any:
    if isinstance(value, float):
        raise ValueError(
            "give decimal amounts as a string or an integer; a float has already lost precision"
        )
    return value


#: A Decimal that cannot be fed by a float, and that serialises as string-or-integer in
#: JSON Schema. Closes the precision hole a bare `Decimal` leaves at the JSON-RPC edge.
Exact = Annotated[
    Decimal,
    BeforeValidator(_reject_float),
    WithJsonSchema(
        {
            "anyOf": [{"type": "string"}, {"type": "integer"}],
            "description": "Decimal amount as a string or an integer; floats are rejected.",
        }
    ),
]


#: A Decimal on the result side. Pydantic already serialises it to a string in JSON mode,
#: but the default schema says `anyOf[number, string]` — which tells a consumer a number
#: is possible and invites it to parse into a float, throwing away the precision the
#: engine just spent an ADR protecting. The schema must say what the wire actually
#: carries.
Amount = Annotated[
    Decimal,
    WithJsonSchema({"type": "string", "description": "Decimal amount, serialised as a string."}),
]


class ResourceLine(FrozenModel):
    """One line of an APU composition.

    `partial_cost` is derived, never supplied: the engine owns the per-line stage
    (`quantity * unit_price * (1 + waste_pct / 100)`) because that is where the waste
    factor is applied, and a caller that supplied it could apply it twice.
    """

    resource_id: str = Field(min_length=1, max_length=MAX_ID_LENGTH)
    category: str = Field(min_length=1, max_length=MAX_ID_LENGTH)
    quantity: Exact = Field(gt=0)
    unit_price: Exact = Field(ge=0)
    waste_pct: Exact = Field(ge=0, le=100)
    currency: str = Field(min_length=1, max_length=MAX_ID_LENGTH)


class CostFactors(FrozenModel):
    """The six percentage factors of the cascade.

    All six are required. Defaulting them is tempting and wrong: an engine that defaults
    a tax rate to zero produces a plausible number nobody chose. What the caller did not
    declare is a contract error.
    """

    tool_wear_pct: Exact = Field(ge=0, le=100)
    safety_equipment_pct: Exact = Field(ge=0, le=100)
    indirect_cost_pct: Exact = Field(ge=0, le=100)
    financing_pct: Exact = Field(ge=0, le=100)
    utility_pct: Exact = Field(ge=0, le=100)
    tax_pct: Exact = Field(ge=0, le=100)


class RoundingPolicy(FrozenModel):
    """When and how the cascade rounds. See ADR 0001.

    `exact`     - never quantise; reproduces full-precision Decimal arithmetic.
    `final`     - exact intermediates, final unit cost quantised (the default).
    `per-stage` - quantise every stage before it feeds the next.
    """

    mode: Literal["exact", "final", "per-stage"] = "final"
    money_scale: int = Field(default=4, ge=0, le=MAX_MONEY_SCALE)


class CostStage(FrozenModel):
    name: str
    amount: Amount


class CategoryCost(FrozenModel):
    category: str
    cost: Amount


class CostCascadeResult(FrozenModel):
    contract_version: Literal["cost-cascade.v1"] = "cost-cascade.v1"
    success: bool
    currency: str = ""
    categories: tuple[CategoryCost, ...] = ()
    stages: tuple[CostStage, ...] = ()
    unit_cost: Amount | None = None
    rounding: RoundingPolicy | None = None
    truncated: Literal[False] = False
    diagnostics: tuple[Diagnostic, ...] = ()


class DimensionCheckResult(FrozenModel):
    contract_version: Literal["dimension-check.v1"] = "dimension-check.v1"
    success: bool
    compatible: bool = False
    satisfiable: bool = False
    quantity_field: str = ""
    unit_category: str = ""
    expected_field: str | None = None
    folded_symbol: str | None = None
    truncated: Literal[False] = False
    diagnostics: tuple[Diagnostic, ...] = ()


class Capabilities(FrozenModel):
    engine: str = "motor-costos"
    version: str
    contract_versions: tuple[str, ...]
    rounding_modes: tuple[str, ...]
    default_rounding_mode: str
    default_money_scale: int
    engine_precision: int
    quantity_fields: tuple[str, ...]
    satisfiable_unit_categories: tuple[str, ...]
    unit_categories: tuple[str, ...]
    max_resource_lines: int
    max_categories: int
    max_nesting_depth: int
    currency_conversion: Literal[False] = False
    unit_conversion: Literal[False] = False
    publication: Literal["none"] = "none"
