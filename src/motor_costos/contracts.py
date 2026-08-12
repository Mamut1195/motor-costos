"""Versioned input contracts.

Contracts are versioned by name ("cost-cascade.v1"), never "the API". New versions are
additive: v1 stays byte-stable once shipped.

`CONTRACTS` is the single registry. `capabilities()` and the JSON Schema generator both
derive from it, so a contract cannot be added without appearing in both. Restating the
version tuple in the Capabilities model instead would let a contract ship undeclared.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from motor_costos.models import (
    MAX_ID_LENGTH,
    CostCascadeResult,
    CostFactors,
    DimensionCheckResult,
    FrozenModel,
    ResourceLine,
    RoundingPolicy,
)

#: Upper bound on the declared taxonomy.
#:
#: Deliberately NOT a pydantic `max_length` on the field. A limit expressed there raises
#: a ValidationError, which is a raw third-party exception the caller must catch; a limit
#: checked in `cascade._validate` returns a typed diagnostic like every other refusal.
#: It is also why the boundary is reachable from a test at all: a `max_length` is baked
#: into the model at class-definition time and no monkeypatch can move it, so its
#: boundary test could never fail for the reason it claims.
MAX_CATEGORIES = 64

#: Lines per composition. Same reasoning as above.
MAX_RESOURCE_LINES = 10_000

#: An APU cannot contain another APU. The domain this was translated from has no
#: mechanism for it -- no self reference, no polymorphic target -- so the engine declares
#: the depth rather than half-supporting nesting it cannot verify.
MAX_NESTING_DEPTH = 1


class CostCascadeV1(FrozenModel):
    """Input for the unit-price cascade over an APU composition.

    The category taxonomy and the labour category are declared, never assumed: see
    ADR 0003. The labour category is the base of the tool-wear and safety surcharges,
    which belong to direct cost, before the compounding cascade begins.
    """

    contract_version: Literal["cost-cascade.v1"] = "cost-cascade.v1"
    categories: tuple[str, ...] = Field(min_length=1)
    labour_category: str = Field(min_length=1, max_length=MAX_ID_LENGTH)
    lines: tuple[ResourceLine, ...] = ()
    factors: CostFactors
    rounding: RoundingPolicy = RoundingPolicy()

    @model_validator(mode="after")
    def unique_categories(self) -> CostCascadeV1:
        if len(set(self.categories)) != len(self.categories):
            raise ValueError("categories must be unique")
        return self


class DimensionCheckV1(FrozenModel):
    """Input for dimensional compatibility.

    `unit_category` is authoritative and required; the engine never infers it from the
    symbol. `unit_symbol` is optional: when given it is folded and cross-checked against
    the vocabulary, and a disagreement is reported rather than resolved.
    """

    contract_version: Literal["dimension-check.v1"] = "dimension-check.v1"
    quantity_field: str = Field(max_length=MAX_ID_LENGTH)
    unit_category: str = Field(max_length=MAX_ID_LENGTH)
    unit_symbol: str | None = Field(default=None, max_length=MAX_ID_LENGTH)


#: The registry. Order is the published order of `capabilities().contract_versions`.
CONTRACTS: dict[str, type[FrozenModel]] = {
    "cost-cascade.v1": CostCascadeV1,
    "dimension-check.v1": DimensionCheckV1,
}

#: The result type each contract returns. Keyed by the same names, so a contract cannot
#: gain an input schema without gaining a result schema.
RESULTS: dict[str, type[FrozenModel]] = {
    "cost-cascade.v1": CostCascadeResult,
    "dimension-check.v1": DimensionCheckResult,
}
