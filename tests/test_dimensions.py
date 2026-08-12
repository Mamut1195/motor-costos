"""`dimension-check.v1` — the contract that makes the measured billing defect impossible.

Seven of ten line items were invoiced with the correct quantity written against the
wrong unit: a volume in cubic metres billed against an APU priced by the linear metre.
Every control passed, because each asked a different question — the value was positive,
the field existed, the rule matched. Nothing compared the dimension of the field with
the dimension of the unit.

The correspondence is ported from a prior in-house map and pinned here against the same
taxonomy it came from.
"""

from __future__ import annotations

from conftest import dimension

from motor_costos import DiagnosticCode, check_dimension
from motor_costos.dimensions import (
    CATEGORY_BY_TOKEN,
    QUANTITY_FIELD_UNIT_CATEGORY,
    UNIT_CATEGORIES,
    UNIT_CATEGORY_QUANTITY_FIELD,
)

CORRESPONDENCE = {
    "area": "area",
    "volume": "volume",
    "length": "length",
    "count": "unit",
    "weight": "weight",
}

UNSATISFIABLE = ("time", "capacity", "other")


def test_each_quantity_field_matches_its_own_unit_category():
    for field, category in CORRESPONDENCE.items():
        result = check_dimension(dimension(field, category))
        assert result.success, result.diagnostics
        assert result.compatible, field


def test_the_correspondence_is_the_intended_one():
    """Pins the map itself, not just its behaviour."""
    for field, category in CORRESPONDENCE.items():
        result = check_dimension(dimension("area", category))
        assert result.expected_field == field, category


def test_the_measured_defect_is_rejected():
    """A volume quantity against a length-priced APU: incompatible, and it names the fix."""
    result = check_dimension(dimension("volume", "length"))
    assert result.success, result.diagnostics
    assert not result.compatible
    assert result.expected_field == "length"


def test_every_cross_pairing_is_incompatible():
    for field in CORRESPONDENCE:
        for other_field, category in CORRESPONDENCE.items():
            if field == other_field:
                continue
            result = check_dimension(dimension(field, category))
            assert not result.compatible, f"{field} vs {category}"


def test_lump_sum_and_time_can_never_be_satisfied():
    """TIME, CAPACITY and OTHER are deliberately absent from the map: an APU priced
    in hours, gallons or 'global' measures no physical dimension, so no quantity
    satisfies it (units.py:64-65)."""
    for category in UNSATISFIABLE:
        for field in CORRESPONDENCE:
            result = check_dimension(dimension(field, category))
            assert result.success, result.diagnostics
            assert not result.satisfiable, category
            assert not result.compatible
            assert result.expected_field is None


def test_an_unknown_quantity_field_is_a_contract_error():
    result = check_dimension(dimension("perimeter", "length"))
    assert not result.success
    assert DiagnosticCode.UNKNOWN_QUANTITY_FIELD in [d.code for d in result.diagnostics]


def test_an_unknown_unit_category_is_a_contract_error():
    result = check_dimension(dimension("length", "luminosity"))
    assert not result.success
    assert DiagnosticCode.UNKNOWN_UNIT_CATEGORY in [d.code for d in result.diagnostics]


def test_an_undeclared_unit_category_is_a_contract_error():
    """`UnitOfMeasure.category` has no default in the reference, so '' is reachable
    (D5). The engine refuses to guess what an empty category meant."""
    result = check_dimension(dimension("length", ""))
    assert not result.success
    assert DiagnosticCode.UNKNOWN_UNIT_CATEGORY in [d.code for d in result.diagnostics]


def test_a_symbol_agreeing_with_the_declared_category_is_silent():
    result = check_dimension(dimension("volume", "volume", unit_symbol="m3"))
    assert result.success, result.diagnostics
    assert result.compatible
    assert result.diagnostics == ()


def test_symbol_folding_matches_the_reference():
    """fold_unit_symbol('M2') == fold_unit_symbol('m²') == fold_unit_symbol(' M. 2 ')."""
    for symbol in ("M2", "m²", " M. 2 "):
        result = check_dimension(dimension("area", "area", unit_symbol=symbol))
        assert result.success, result.diagnostics
        assert result.folded_symbol == "m2", symbol


def test_a_symbol_contradicting_its_declared_category_warns():
    """D3: the seed creates `glb` as category `unit`, while the inference vocabulary
    maps it to `other`. Since count -> unit, that lets a count quantity satisfy a
    lump-sum price today. The engine does not infer, but it does report the conflict."""
    result = check_dimension(dimension("count", "unit", unit_symbol="glb"))
    assert result.success, result.diagnostics
    assert DiagnosticCode.SYMBOL_CATEGORY_CONFLICT in [d.code for d in result.diagnostics]


def test_a_symbol_outside_the_vocabulary_warns_rather_than_guessing():
    """D4: seven of the 32 seeded symbols are unknown to the inference vocabulary."""
    for symbol in ("pie", "pie2", "pie3", "yd3", "sem", "jgo", "funda"):
        result = check_dimension(dimension("length", "length", unit_symbol=symbol))
        assert result.success, result.diagnostics
        assert DiagnosticCode.UNKNOWN_UNIT_SYMBOL in [d.code for d in result.diagnostics], symbol


def test_the_vocabulary_and_taxonomy_sizes_are_pinned():
    """The README states these numbers; nothing else would stop them drifting."""
    assert len(CATEGORY_BY_TOKEN) == 67
    assert len(UNIT_CATEGORIES) == 8
    assert len(QUANTITY_FIELD_UNIT_CATEGORY) == 5
    assert len(UNIT_CATEGORY_QUANTITY_FIELD) == 5
    assert set(UNSATISFIABLE) == set(UNIT_CATEGORIES) - set(CORRESPONDENCE.values())


def test_the_inverse_map_is_derived_not_written_twice():
    assert UNIT_CATEGORY_QUANTITY_FIELD == {
        category: field for field, category in QUANTITY_FIELD_UNIT_CATEGORY.items()
    }
