# ADR 0001: The rounding policy is a contract input, defaulting to exact intermediates with a half-up final quantisation

**Status:** Accepted

## Context

The implementation this engine was translated from never rounds inside the cascade. It contains
no `quantize`, no `round`, and no explicit `decimal.Context`; full-precision values are handed to
a database, and the column scale does the rounding on write. The behaviour is consistent, so
there was no defect — but **the policy lived in the database schema, not in the code**. An engine
has no database. Extracting the cascade forces the policy to be written down, and that is half
the value of the extraction.

Three candidate policies were evaluated:

- **Exact.** Never quantise. Reproduces the source implementation's in-memory value exactly.
  Precision grows without a ceiling and the caller is left to round — which is the very problem
  this engine exists to solve.
- **Exact intermediates, quantised final.** The cascade runs in exact `Decimal`; only the final
  unit cost is quantised. Reproduces every intermediate, bounds the output, and lands on the
  value that is actually persisted and invoiced.
- **Per stage.** Quantise every stage before it feeds the next. This is what an estimator with a
  spreadsheet does, and it makes a composition auditable line by line — but it reproduces none of
  the source implementation's intermediate values.

A tempting way to choose was to measure which mode reproduces the values pinned by the source's
mutation suites. **That method does not work**, and finding out why was worth more than the
answer: those suites pin no cascade value at all. They define a hand-written mirror of the
formula and assert only `mutated != correct`. A handful of values are pinned elsewhere, but all
of them belong to the per-line stage with every factor set to zero, so none exercises rounding.

The one usable oracle is a full cascade with all six factors non-zero:

| Stage | Pinned value |
|---|---|
| `direct_cost` | `27.00` |
| `subtotal_1` | `32.40` |
| `subtotal_2` | `33.048` |
| `subtotal_3` | `37.01376` |
| `unit_cost` | `42.9359616` |

Seven decimals survive to the end. That proves no stage is rounded: quantising each stage to four
decimals would turn `37.01376` into `37.0138` and change the result, and quantising only at the
end could not produce seven decimals.

The mode, where that domain does round, is `ROUND_HALF_UP`. It is pinned with tie cases chosen to
distinguish it from banker's rounding — `0.005 → 0.01`, where banker's gives `0.00`, and
`1234.565 → 1234.57`, where banker's gives `1234.56` — but it lives only in the presentation
layer.

Scale expectations across that domain: money at four decimals, percentages at two, quantities at
six, denormalised sums at four with more headroom.

## Decision

The policy is a field of the contract input, never a hidden constant. Three modes are supported:

| Mode | Intermediates | Final |
|---|---|---|
| `exact` | exact | exact |
| `final` (**default**) | exact | quantised to `money_scale`, `ROUND_HALF_UP` |
| `per-stage` | quantised to `money_scale`, `ROUND_HALF_UP` | quantised |

The default is `final` with `money_scale = 4`, so the oracle's five intermediates are reproduced
exactly and `unit_cost` resolves to `42.9360` — the value a decimal column of scale 4 stores, and
therefore the value that gets invoiced.

`ROUND_HALF_UP` is the only rounding mode offered. Banker's rounding is not selectable: the
domain has already declared half-up as its convention and pinned it with tie cases, and offering
a second mode would invite the inconsistency described below.

Every public entry point runs its arithmetic inside an explicit `decimal.localcontext()` with a
fixed precision of 28 significant digits. The engine never reads the caller's global context.

## Contract boundary

Determinism is the deciding constraint. An implementation that leaves rounding implicit
accumulates variants: none in the calculation, one at the database boundary, another at
presentation, and — in at least one money path of the source implementation — a bare `quantize`
with no `rounding` argument, which is banker's rounding applied to money, contradicting the
convention its own oracle pins. An engine that inherited an implicit policy would inherit that
ambiguity. Naming the policy in the contract makes the caller's choice explicit and auditable,
and makes a silent fifth variant impossible.

Making the policy an input rather than a constant is also what keeps the engine country- and
trade-agnostic. A different jurisdiction, currency, or trade will want a different scale; that is
a caller's decision, not the engine's. What the engine refuses to do is guess: an absent policy
resolves to the documented default, and an unsupported mode is a contract error, never a silent
fallback.

Unbounded intermediate precision is a real failure mode, not a theoretical one. Nothing in the
source implementation caps the scale of an intermediate, and the destination column holds
fourteen digits. A long enough composition can exceed that and raise a database exception instead
of rounding. The engine therefore verifies magnitude ceilings **before** calculating and fails
the whole computation with a diagnostic, rather than producing a partial result.

One consequence is worth stating because it is easy to miss: the engine preserves the *exponent*
the arithmetic produces, not only the value. `subtotal_3` is `37.0137600000`, not `37.01376`,
because `25.00 * 5.00` is `125.0000` and dividing by 100 preserves that scale. An oracle written
with `==` never notices, since `Decimal` compares by value — but a consumer reading the
serialised string does. Renormalising would silently change what that consumer receives, so the
engine does not, and the behaviour is pinned by a test rather than left to be discovered.

## Rollback

Delete `src/motor_costos/rounding.py` and the `rounding` field from `CostCascadeV1`. The cascade
then runs in whatever context the caller supplies, matching the implicit behaviour this ADR
replaced and forfeiting the determinism guarantee. `tests/test_rounding.py` and the
`unit_cost == 42.9360` assertion in `tests/test_cascade.py` must be removed with it; the
`42.9359616` oracle stays, because it holds under `exact`.
