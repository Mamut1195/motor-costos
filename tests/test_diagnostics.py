"""The diagnostic contract: stable codes, uniform shape, and nothing leaked.

A diagnostic is the only thing a caller sees when a computation refuses, so its shape is
as much a contract as the result. What must never appear in one: a filesystem path, a
third-party exception message, a stack trace, or an unbounded string.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from conftest import cascade, dimension, line
from motor_costos import Diagnostic, DiagnosticCode, check_dimension, compute_cascade
from motor_costos.diagnostics import MAX_MESSAGE_LENGTH, error, warning


def every_diagnostic():
    """One of every diagnostic the engine can emit through its public entry points."""
    produced = []
    scenarios = [
        cascade([line("XX", quantity="1", unit_price="1")]),
        cascade([], categories=("MAT",), labour_category="MO"),
        cascade(
            [
                line("MAT", quantity="1", unit_price="1", resource_id="a"),
                line("MO", quantity="1", unit_price="1", resource_id="a"),
            ]
        ),
        cascade(
            [
                line("MAT", quantity="1", unit_price="1", currency="USD"),
                line("MO", quantity="1", unit_price="1", currency="PEN"),
            ]
        ),
        cascade([line("MAT", quantity="1", unit_price="10000000000")]),
        cascade([line("MAT", quantity="1000000", unit_price="1000000")]),
    ]
    for contract in scenarios:
        produced.extend(compute_cascade(contract).diagnostics)
    for check in (
        dimension("perimeter", "length"),
        dimension("length", "luminosity"),
        dimension("length", "length", unit_symbol="yd3"),
        dimension("count", "unit", unit_symbol="glb"),
    ):
        produced.extend(check_dimension(check).diagnostics)
    return produced


def test_every_declared_code_has_an_emitter():
    """No orphan codes.

    A diagnostic code is contract surface: publishing one the engine never emits promises
    behaviour that does not exist. Four codes were declared during development and never
    emitted — `CONTRACT_VALIDATION`, `LIMIT_NESTING_DEPTH`, `UNSUPPORTED_ROUNDING_MODE`
    and `RPC_INTERNAL` — and were deleted rather than documented as unreachable. This
    keeps the property verified instead of annotated.
    """
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (Path(__file__).resolve().parent.parent / "src" / "motor_costos").glob("*.py")
    )
    for code in DiagnosticCode:
        # The enum declaration itself is `NAME = 30xx`, without the `DiagnosticCode.`
        # prefix, so any prefixed occurrence in src/ is an emitter.
        assert f"DiagnosticCode.{code.name}" in source, (
            f"{code.name} is declared but never emitted"
        )


def test_the_scenarios_cover_every_caller_triggerable_code():
    """Guards the sweep below: a new caller-facing code without a scenario fails here."""
    emitted = {d.code for d in every_diagnostic()}
    covered_elsewhere = {
        # Boundary codes: exercised under monkeypatch in test_limits.py, because
        # constructing 10,001 real lines to reach them would be slower and no stronger.
        DiagnosticCode.LIMIT_RESOURCE_LINES,
        DiagnosticCode.LIMIT_CATEGORIES,
        DiagnosticCode.LIMIT_DIAGNOSTICS,
        # An engine defect, not a caller error. Reached by the DROP_TOOL_FROM_DIRECT_COST
        # mutant in test_mutation.py, which is the only honest way to provoke it.
        DiagnosticCode.RECONCILIATION_FAILED,
    }
    assert emitted == {int(code) for code in DiagnosticCode} - {
        int(code) for code in covered_elsewhere
    }


@pytest.mark.parametrize("diagnostic", every_diagnostic(), ids=lambda d: str(d.code))
def test_every_diagnostic_has_the_same_shape(diagnostic: Diagnostic):
    assert diagnostic.severity in ("error", "warning", "info")
    assert diagnostic.stage in ("cost-cascade.v1", "dimension-check.v1")
    assert diagnostic.message.strip()
    assert diagnostic.message.endswith(".")
    assert diagnostic.suggested_action.strip(), "every diagnostic must say what to do"
    assert diagnostic.suggested_action.endswith(".")


@pytest.mark.parametrize("diagnostic", every_diagnostic(), ids=lambda d: str(d.code))
def test_no_diagnostic_leaks_a_path_or_an_exception(diagnostic: Diagnostic):
    text = " ".join(
        (diagnostic.message, diagnostic.suggested_action, *diagnostic.context)
    )
    assert "\\" not in text
    assert "C:" not in text
    assert "Traceback" not in text
    assert "motor_costos" not in text
    assert "pydantic" not in text.lower()
    assert ".py" not in text


@pytest.mark.parametrize("diagnostic", every_diagnostic(), ids=lambda d: str(d.code))
def test_every_string_is_bounded(diagnostic: Diagnostic):
    assert len(diagnostic.message) <= MAX_MESSAGE_LENGTH
    assert len(diagnostic.suggested_action) <= MAX_MESSAGE_LENGTH
    for entry in diagnostic.context:
        assert len(entry) <= MAX_MESSAGE_LENGTH + len(entry.split("=", 1)[0]) + 1


def test_caller_text_reaching_a_diagnostic_is_clipped():
    """The only untrusted text a diagnostic can carry is context, and it is bounded."""
    clipped = error(
        DiagnosticCode.CURRENCY_MISMATCH, "s", "m.", "a.", symbol="x" * (MAX_MESSAGE_LENGTH * 3)
    )
    assert len(clipped.context[0]) == MAX_MESSAGE_LENGTH + len("symbol=")


def test_context_is_sorted_so_two_runs_serialise_identically():
    diagnostic = error(DiagnosticCode.CURRENCY_MISMATCH, "s", "m.", "a.", z=1, a=2, m=3)
    assert diagnostic.context == ("a=2", "m=3", "z=1")


def test_a_warning_is_an_error_with_its_severity_changed():
    as_error = error(DiagnosticCode.UNKNOWN_UNIT_SYMBOL, "s", "m.", "a.", k=1)
    as_warning = warning(DiagnosticCode.UNKNOWN_UNIT_SYMBOL, "s", "m.", "a.", k=1)
    assert as_warning.severity == "warning"
    assert as_warning.model_copy(update={"severity": "error"}) == as_error


def test_a_warning_does_not_fail_the_computation():
    result = check_dimension(dimension("count", "unit", unit_symbol="glb"))
    assert result.success
    assert all(d.severity == "warning" for d in result.diagnostics)


def test_codes_are_unique_and_grouped_in_blocks_of_one_hundred():
    values = [int(code) for code in DiagnosticCode]
    assert len(values) == len(set(values))
    assert all(3000 <= value < 4000 for value in values), "motor-costos owns the 3000s"
    blocks = {value // 100 for value in values}
    # 33 (rounding) and 36 (transport) held only orphan codes and are now empty. The gaps
    # stay: a removed code's number is never reused.
    assert blocks == {30, 31, 32, 34, 35}


def test_the_code_serialises_as_a_plain_integer():
    diagnostic = error(DiagnosticCode.CURRENCY_MISMATCH, "s", "m.", "a.")
    assert diagnostic.model_dump(mode="json")["code"] == 3200
    assert type(diagnostic.model_dump(mode="json")["code"]) is int


def test_a_diagnostic_is_frozen_and_closed():
    """Both refusals are pydantic's, and naming the type is the point.

    `pytest.raises(Exception)` would pass on a `TypeError` from a mistyped keyword, which
    is a broken test rather than a frozen model. Frozen assignment and a forbidden extra
    field both raise `ValidationError`, so that is what is asserted.
    """
    diagnostic = error(DiagnosticCode.CURRENCY_MISMATCH, "s", "m.", "a.")
    with pytest.raises(ValidationError):
        diagnostic.code = 1
    with pytest.raises(ValidationError):
        Diagnostic(
            severity="error",
            code=1,
            stage="s",
            message="m",
            suggested_action="a",
            path="/tmp",  # noqa: S108 - a fixture string; this asserts the field cannot exist
        )


def test_the_diagnostic_model_has_no_field_for_a_path_or_an_exception():
    """Structural, not behavioural: leaking is impossible, not merely avoided."""
    assert set(Diagnostic.model_fields) == {
        "severity",
        "code",
        "stage",
        "message",
        "suggested_action",
        "json_pointer",
        "resource_id",
        "context",
    }
