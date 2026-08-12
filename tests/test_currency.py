"""The single-currency invariant.

The engine converts nothing. Two currencies in one composition is a contract error,
rejected before any cost is summed — that ordering is part of the invariant, not an
optimisation.

One deliberate divergence from the implementation this was translated from: reporting the
mismatch as `expected`/`found` after sorting the currencies alphabetically states a
precedence that does not exist ("X is already in use" is simply false when X merely sorts
first), and with three or more currencies it names only two. The engine reports the
complete sorted set and asserts nothing about which one governs.
"""

from __future__ import annotations

from decimal import Decimal

from conftest import cascade, codes, line

from motor_costos import DiagnosticCode, compute_cascade


def test_single_currency_composition_computes_and_reports_its_currency():
    """Ported from test_currency_invariant.py:81-101: USD, price 10, qty 2, no factors."""
    result = compute_cascade(
        cascade(
            [
                line("MAT", quantity="2", unit_price="10", currency="USD"),
            ]
        )
    )
    assert result.success, result.diagnostics
    assert result.unit_cost == Decimal("20.0000")
    assert result.currency == "USD"


def test_two_lines_sharing_a_currency_are_accepted():
    result = compute_cascade(
        cascade(
            [
                line("MAT", quantity="1", unit_price="10", currency="PEN"),
                line("MO", quantity="1", unit_price="20", currency="PEN"),
            ]
        )
    )
    assert result.success, result.diagnostics
    assert result.currency == "PEN"


def test_empty_composition_has_no_currency():
    """Ported from test_currency_invariant.py:46-51."""
    result = compute_cascade(cascade([]))
    assert result.success, result.diagnostics
    assert result.currency == ""


def test_mixed_currencies_are_a_contract_error():
    """Ported from test_currency_invariant.py:55-77."""
    result = compute_cascade(
        cascade(
            [
                line("MAT", quantity="1", unit_price="10", currency="USD"),
                line("MO", quantity="1", unit_price="20", currency="PEN"),
            ]
        )
    )
    assert not result.success
    assert DiagnosticCode.CURRENCY_MISMATCH in codes(result)


def test_mixed_currency_result_is_atomic_never_partial():
    """Rejected before summing: no stages, no breakdown, no unit cost."""
    result = compute_cascade(
        cascade(
            [
                line("MAT", quantity="1", unit_price="10", currency="USD"),
                line("MO", quantity="1", unit_price="20", currency="MXN"),
            ]
        )
    )
    assert not result.success
    assert result.stages == ()
    assert result.categories == ()
    assert result.unit_cost is None


def test_all_conflicting_currencies_are_reported_not_just_two():
    """Sorting the currencies and naming the first two hides every one after them."""
    result = compute_cascade(
        cascade(
            [
                line("MAT", quantity="1", unit_price="1", currency="USD"),
                line("MO", quantity="1", unit_price="1", currency="PEN"),
                line("EQ", quantity="1", unit_price="1", currency="MXN"),
            ]
        )
    )
    assert not result.success
    mismatch = next(d for d in result.diagnostics if d.code == DiagnosticCode.CURRENCY_MISMATCH)
    assert mismatch.context == ("currencies=MXN,PEN,USD",)


def test_currency_is_folded_before_comparison():
    """' usd ' and 'USD' are one currency, as in the reference's strip().upper()."""
    result = compute_cascade(
        cascade(
            [
                line("MAT", quantity="1", unit_price="10", currency=" usd "),
                line("MO", quantity="1", unit_price="20", currency="USD"),
            ]
        )
    )
    assert result.success, result.diagnostics
    assert result.currency == "USD"
