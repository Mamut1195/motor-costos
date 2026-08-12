# ADR 0002: Dimensional compatibility uses an owned category map, not `pint`

**Status:** Accepted

## Context

`dimension-check.v1` exists because of a failure mode that ordinary validation cannot catch: a
quantity that is correct, positive, and stored in a field that exists, but measured in a
dimension the APU is not priced in — a volume in cubic metres billed against a price per linear
metre. Every check passes, because each one asks a different question: is the value positive,
does the field exist, does the rule match. Nothing compares the dimension of the field with the
dimension of the unit, and the invoice is wrong by the ratio between two units nobody compared.

That failure has been observed in practice, which is why this contract exists at all rather than
being left to the caller.

The implementation this engine was translated from resolves dimensions with a hand-written
five-entry map whose inverse is derived by inverting it. The candidates for the engine:

- **`pint`** — the established Python units library, with a real unit registry and conversion.
- **An owned category map** — a closed table from quantity field to unit category, plus a symbol
  folding function.

## Decision

An owned map. `pint` is not a dependency.

The engine ships `dimensions.py` with the field↔category correspondence, the inverse derived by
inversion, a `fold_unit_symbol` normaliser, and the symbol→category vocabulary. Unit categories
are declared by the caller; they are never inferred.

## Contract boundary

The contract is dimensional **classification**, not conversion. `pint`'s value is converting
between commensurable units — metres to centimetres, kilograms to pounds — which is precisely
what this engine promises never to do: it does not convert currencies, does not convert between
dimensions, and never invents a density or a factor. Buying a conversion engine to answer a
classification question imports capability the contract forbids using.

The domain's vocabulary is not physical. Symbols for a lump sum, a sack, a bundle, a hundredweight,
a trip or a set are ordinary units of sale in construction estimating, and `pint` knows none of
them. They would have to be defined by hand in a custom registry regardless, leaving the
dependency carrying only the part of the problem the contract already excludes. The written forms
diverge too: estimators write `m2` and `m3`, where `pint` expects `m**2` or `m²`.

There is also no existing `pint` vocabulary to stay compatible with, so adopting it would
introduce a second notation rather than match one already in use.

Finally, this engine keeps runtime dependencies to what the contract actually uses. It has
exactly one (`pydantic`), and any heavier runtime would belong in an optional extra with an exact
pin and a written justification. Adding `pint` — and with it `flexparser`, `flexcache` and
`platformdirs` — to answer questions about a closed table of eight categories would not meet that
bar.

The engine deliberately keeps `TIME`, `CAPACITY` and `OTHER` outside the satisfiable categories:
an APU priced in hours, gallons or "global" measures no physical dimension, so no quantity can
ever satisfy it dimensionally. That exclusion is a domain judgement, not a limitation of any
library, and it survives the choice made here.

## Rollback

Add `pint` to `dependencies` with an exact pin, replace the category table in
`src/motor_costos/dimensions.py` with a `UnitRegistry` plus a custom definitions file covering
the non-physical symbols, and map `pint` dimensionalities onto the eight domain categories. The
public signature of `check_dimension` does not change, so `tests/test_dimensions.py` stays valid
and becomes the conformance suite for the replacement.
