"""`dimension-check.v1` — dimensional compatibility between a quantity field and a unit.

This contract exists because of a failure mode that ordinary validation cannot catch: a
quantity that is correct, positive, and stored in a field that exists, but measured in a
dimension the APU is not priced in — a volume in cubic metres billed against a price per
linear metre. Every check passes, because each one asks a different question. Nothing
compares the dimension of the field with the dimension of the unit, so the invoice is
wrong by the ratio between two units nobody compared.

The correspondence is translated from a prior in-house map; the inverse is derived by
inverting it, never written twice. The taxonomy and the symbol vocabulary come from the
same source.

TIME, CAPACITY and OTHER are deliberately absent from the correspondence: an APU priced
in hours, gallons or "global" measures no physical dimension, so no quantity can satisfy
it. That exclusion is a domain judgement and it is preserved here.

No unit library. See ADR 0002.
"""

from __future__ import annotations

from motor_costos.contracts import DimensionCheckV1
from motor_costos.diagnostics import Diagnostic, DiagnosticCode, error, warning
from motor_costos.models import DimensionCheckResult

_STAGE = "dimension-check.v1"

#: Quantity field -> unit category. The whole of the correspondence.
QUANTITY_FIELD_UNIT_CATEGORY: dict[str, str] = {
    "area": "area",
    "volume": "volume",
    "length": "length",
    "count": "unit",
    "weight": "weight",
}

#: Derived by inversion, so the two can never disagree.
UNIT_CATEGORY_QUANTITY_FIELD: dict[str, str] = {
    category: field for field, category in QUANTITY_FIELD_UNIT_CATEGORY.items()
}

QUANTITY_FIELDS: tuple[str, ...] = tuple(QUANTITY_FIELD_UNIT_CATEGORY)

#: Categories a quantity can satisfy.
SATISFIABLE_UNIT_CATEGORIES: tuple[str, ...] = tuple(UNIT_CATEGORY_QUANTITY_FIELD)

#: The full taxonomy.
UNIT_CATEGORIES: tuple[str, ...] = (
    "length",
    "area",
    "volume",
    "weight",
    "time",
    "unit",
    "capacity",
    "other",
)

_EXPONENT_DIGITS = str.maketrans({"¹": "1", "²": "2", "³": "3"})


def fold_unit_symbol(symbol: str) -> str:
    """Normalise a written unit symbol.

    `M2`, `m²` and ` M. 2 ` all fold to `m2`.
    """
    folded = (symbol or "").translate(_EXPONENT_DIGITS).casefold()
    return "".join(ch for ch in folded if not ch.isspace() and ch != ".")


#: Folded symbol -> unit category. Used only to cross-check a declared category, never
#: to infer one.
CATEGORY_BY_TOKEN: dict[str, str] = {
    # length
    "m": "length", "ml": "length", "mts": "length", "km": "length", "cm": "length",
    "mm": "length", "in": "length", "ft": "length", "pulg": "length",
    # area
    "m2": "area", "ft2": "area", "cm2": "area", "km2": "area", "ha": "area",
    # volume
    "m3": "volume", "cm3": "volume", "ft3": "volume",
    # weight
    "kg": "weight", "g": "weight", "tn": "weight", "ton": "weight", "t": "weight",
    "lb": "weight", "qq": "weight",
    # capacity
    "l": "capacity", "lt": "capacity", "lts": "capacity", "gl": "capacity",
    "gal": "capacity", "gln": "capacity", "galon": "capacity", "m3l": "capacity",
    # time
    "h": "time", "hr": "time", "hra": "time", "hora": "time", "horas": "time",
    "dia": "time", "día": "time", "dias": "time", "jornal": "time", "mes": "time",
    "semana": "time", "min": "time",
    # unit
    "u": "unit", "un": "unit", "ud": "unit", "und": "unit", "uds": "unit", "unidad": "unit",
    "pza": "unit", "pieza": "unit", "pto": "unit", "pt": "unit", "punto": "unit",
    "bolsa": "unit", "saco": "unit", "rollo": "unit", "lote": "unit", "viaje": "unit",
    "pliego": "unit", "varilla": "unit", "par": "unit", "juego": "unit",
    "tramo": "unit", "cja": "unit", "caja": "unit",
    # explicitly dimensionless
    "global": "other", "glb": "other", "gbl": "other",
}


def _symbol_diagnostics(symbol: str, folded: str, declared: str) -> tuple[Diagnostic, ...]:
    inferred = CATEGORY_BY_TOKEN.get(folded)
    if inferred is None:
        # A vocabulary is never complete, and a symbol it does not know is not thereby
        # dimensionless. The engine says it could not cross-check, rather than guessing.
        return (
            warning(
                DiagnosticCode.UNKNOWN_UNIT_SYMBOL,
                _STAGE,
                "The unit symbol is outside the known vocabulary and was not cross-checked.",
                "Verify the declared unit category, or add the symbol to the vocabulary.",
                symbol=symbol,
                folded=folded,
            ),
        )
    if inferred != declared:
        # Two sources of truth for one symbol's dimension will disagree eventually. When
        # a lump-sum symbol is classified as a countable one, a count quantity starts
        # satisfying a price that measures nothing -- so the disagreement is reported,
        # never resolved by picking a side.
        return (
            warning(
                DiagnosticCode.SYMBOL_CATEGORY_CONFLICT,
                _STAGE,
                "The unit symbol contradicts the declared unit category.",
                "Correct the declared category, or the symbol; the engine resolves neither.",
                symbol=symbol,
                folded=folded,
                declared=declared,
                vocabulary=inferred,
            ),
        )
    return ()


def check_dimension(contract: DimensionCheckV1) -> DimensionCheckResult:
    """Decide whether a quantity field and a unit category measure the same thing.

    Never raises. A declared category is never inferred from the symbol; when a symbol
    is supplied it is folded and cross-checked, and a disagreement is reported.
    """
    field = contract.quantity_field
    declared = contract.unit_category

    if field not in QUANTITY_FIELD_UNIT_CATEGORY:
        return DimensionCheckResult(
            success=False,
            quantity_field=field,
            unit_category=declared,
            diagnostics=(
                error(
                    DiagnosticCode.UNKNOWN_QUANTITY_FIELD,
                    _STAGE,
                    "The quantity field is not one this engine knows.",
                    "Use one of the declared quantity fields.",
                    quantity_field=field,
                    known=",".join(QUANTITY_FIELDS),
                ),
            ),
        )

    if declared not in UNIT_CATEGORIES:
        # An empty category is reachable wherever the field carries no default. The
        # engine refuses to guess what an undeclared category meant.
        return DimensionCheckResult(
            success=False,
            quantity_field=field,
            unit_category=declared,
            diagnostics=(
                error(
                    DiagnosticCode.UNKNOWN_UNIT_CATEGORY,
                    _STAGE,
                    "The unit category is undeclared or not one this engine knows.",
                    "Declare one of the known unit categories.",
                    unit_category=declared,
                    known=",".join(UNIT_CATEGORIES),
                ),
            ),
        )

    folded = fold_unit_symbol(contract.unit_symbol) if contract.unit_symbol is not None else None
    diagnostics = (
        _symbol_diagnostics(contract.unit_symbol, folded, declared)
        if folded is not None
        else ()
    )

    satisfiable = declared in UNIT_CATEGORY_QUANTITY_FIELD
    return DimensionCheckResult(
        success=True,
        compatible=satisfiable and QUANTITY_FIELD_UNIT_CATEGORY[field] == declared,
        satisfiable=satisfiable,
        quantity_field=field,
        unit_category=declared,
        expected_field=UNIT_CATEGORY_QUANTITY_FIELD.get(declared),
        folded_symbol=folded,
        diagnostics=diagnostics,
    )


__all__ = [
    "CATEGORY_BY_TOKEN",
    "QUANTITY_FIELDS",
    "QUANTITY_FIELD_UNIT_CATEGORY",
    "SATISFIABLE_UNIT_CATEGORIES",
    "UNIT_CATEGORIES",
    "UNIT_CATEGORY_QUANTITY_FIELD",
    "check_dimension",
    "fold_unit_symbol",
]
