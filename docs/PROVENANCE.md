# Provenance

## Runtime dependencies

| Package | Version | License | Why |
|---|---|---|---|
| pydantic | `>=2.12,<3` | MIT | Typed, frozen, closed contracts and results, and the JSON Schema the engine publishes. A caret range rather than an exact pin: the engine depends on v2 validation semantics, not on a patch-level behaviour. |

Test dependencies: pytest (MIT), pytest-cov (MIT). Lint dependency: ruff (MIT), kept in its own
`lint` extra and pinned to a minor — a ruff minor release adds rules, and a linter able to fail CI
on unchanged source would undercut the determinism the two-OS matrix exists to defend.

Standard library only for everything else. `decimal` carries all arithmetic; the engine imports
no third-party numeric or unit library.

**Evaluated and declined:** `pint` (BSD-3-Clause), for the dimensional contract. Declined on the
grounds argued in [`adr/0002-own-dimension-map-not-pint.md`](adr/0002-own-dimension-map-not-pint.md):
the contract classifies dimensions rather than converting them, most of the domain's vocabulary
is non-physical and would need hand definitions anyway, the written forms diverge (`m2` versus
`m**2`), and this engine keeps runtime dependencies to what the contract actually uses.

## Domain knowledge

The cost cascade, the dimensional correspondence and the invariants encoded here were
**translated, not copied,** from a prior in-house implementation that is not part of this
repository and is not published. What was translated is behaviour: the order of the cascade
stages, which base each percentage applies to, the per-line waste factor, the single-currency
rule, the field↔dimension correspondence, and the precision the domain expects of money,
percentages and quantities.

What was deliberately **not** carried over:

- Any ORM, model layer or database coupling. The engine has no persistence and no notion of a
  tenant, a user, a project or a budget.
- The fixed six-category enumeration. The taxonomy is now a contract input
  ([ADR 0003](adr/0003-resource-categories-are-declared-by-the-caller.md)).
- The implicit rounding that relied on a database column's scale. The policy is now explicit and
  parametrised ([ADR 0001](adr/0001-rounding-policy-is-contract-input.md)).
- The partial category breakdown, replaced by an enforced reconciliation invariant.
- The currency-mismatch reporting shape, which asserted a precedence between currencies that does
  not exist.

No source file was copied. Every module here was written from the behaviour described above and
verified against known-answer values.

## Oracles

Known-answer values are carried in the tests themselves, each with a hand derivation in the
docstring, rather than as opaque fixture files. The set covers: a full cascade with all six
factors non-zero and five pinned intermediate stages; the per-line waste factor; the
single-currency invariant; the five-entry dimensional correspondence and the categories no
quantity can satisfy; symbol folding; and the `ROUND_HALF_UP` boundary cases, including two ties
that banker's rounding resolves the other way.

## Reuse rule

Before future reuse, maintainers must document source, license, copyright owner, approval, and
transformation. Ambiguous code must be reimplemented from behaviour and independent tests.
