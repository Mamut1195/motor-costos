"""Stable, safe diagnostics.

Codes are grouped in blocks of 100 by concern, starting at 3000, so that a code
identifies the engine that produced it even when several are composed. Codes
are part of the contract: they are appended to their block, never renumbered and
never recycled.

A diagnostic carries no filesystem path, no exception object and no third-party error
text. Every message and suggested action is a static literal owned by this module's
callers; caller data reaches a diagnostic only through the typed context fields, which
are length-bounded here.
"""

from __future__ import annotations

from enum import IntEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict

#: Hard ceiling on any string this module emits. Messages are static literals, so
#: this never fires for them; it bounds caller-supplied context values, which are the
#: only untrusted text that can reach a result.
MAX_MESSAGE_LENGTH = 1_000


class DiagnosticCode(IntEnum):
    """Every member here must have an emitter. A declared code with no emitter is a
    promise the engine never keeps, and `test_diagnostics.py` fails if one appears.

    Numbers are appended to their block, never renumbered and never recycled — a caller
    switching on 3200 must keep getting a currency mismatch forever. Gaps left by a
    removed code are therefore permanent: 3000, 3005, 3300 and 3600 were declared during
    development, never emitted, and deleted rather than left as decoration.
    """

    # 30xx - contract and limits
    LIMIT_RESOURCE_LINES = 3001
    LIMIT_CATEGORIES = 3002
    LIMIT_MONEY_MAGNITUDE = 3003
    LIMIT_DIAGNOSTICS = 3004

    # 31xx - composition references
    UNDECLARED_CATEGORY = 3100
    UNDECLARED_LABOUR_CATEGORY = 3101
    DUPLICATE_RESOURCE = 3102

    # 32xx - currency
    CURRENCY_MISMATCH = 3200

    # 34xx - cascade invariants
    RECONCILIATION_FAILED = 3400

    # 35xx - dimensional compatibility
    UNKNOWN_QUANTITY_FIELD = 3500
    UNKNOWN_UNIT_CATEGORY = 3501
    UNKNOWN_UNIT_SYMBOL = 3502
    SYMBOL_CATEGORY_CONFLICT = 3503


Severity = Literal["error", "warning", "info"]


class Diagnostic(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    severity: Severity
    code: int
    stage: str
    message: str
    suggested_action: str
    json_pointer: str | None = None
    resource_id: str | None = None
    context: tuple[str, ...] = ()


def _clip(value: object) -> str:
    text = str(value)
    return text if len(text) <= MAX_MESSAGE_LENGTH else text[:MAX_MESSAGE_LENGTH]


def error(
    code: DiagnosticCode,
    stage: str,
    message: str,
    action: str,
    **context: object,
) -> Diagnostic:
    """Build an error diagnostic.

    Context keys are flattened to a sorted `"key=value"` tuple so that two runs over
    the same input serialise identically.
    """
    json_pointer = context.pop("json_pointer", None)
    resource_id = context.pop("resource_id", None)
    return Diagnostic(
        severity="error",
        code=int(code),
        stage=stage,
        message=_clip(message),
        suggested_action=_clip(action),
        json_pointer=_clip(json_pointer) if json_pointer is not None else None,
        resource_id=_clip(resource_id) if resource_id is not None else None,
        context=tuple(f"{key}={_clip(value)}" for key, value in sorted(context.items())),
    )


def warning(
    code: DiagnosticCode,
    stage: str,
    message: str,
    action: str,
    **context: object,
) -> Diagnostic:
    return error(code, stage, message, action, **context).model_copy(
        update={"severity": "warning"}
    )


def cap(diagnostics: tuple[Diagnostic, ...], limit: int, stage: str) -> tuple[Diagnostic, ...]:
    """Bound a diagnostic list, announcing its own truncation.

    Keeps the first `limit - 1` and replaces the tail with one diagnostic that says how
    many were dropped, so a truncated result can never be mistaken for a complete one.
    """
    if len(diagnostics) <= limit:
        return diagnostics
    dropped = len(diagnostics) - (limit - 1)
    return (
        *diagnostics[: limit - 1],
        error(
            DiagnosticCode.LIMIT_DIAGNOSTICS,
            stage,
            "Diagnostic count exceeded the limit and the list was truncated.",
            "Fix the reported problems and run again to see the remainder.",
            dropped=dropped,
            limit=limit,
        ),
    )
