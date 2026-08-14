# motor-costos

Deterministic, stateless, framework-free cost engine. It computes the unit price of an APU from
its composition, and decides whether a quantity field and a unit of measure measure the same
thing. It does **not** quote, hunt prices, suggest resources, convert currencies, convert between
dimensions, infer a missing declaration, or persist anything.

This engine belongs to no application. It does not know what a tenant, a user, a project or a
budget is. It receives data, calculates, and returns typed data.

## Quick path

```powershell
python -m venv .venv; .\.venv\Scripts\Activate.ps1
pip install -e ".[test,lint]"
python -m ruff check .
python -m pytest
motor-costos-sidecar     # NDJSON JSON-RPC 2.0 on stdin/stdout
motor-costos-schemas     # regenerate schemas/
```

## Public API

```python
from motor_costos import capabilities, compute_cascade, check_dimension
```

`capabilities()` declares what this build supports. Its `contract_versions` is derived from the
contract registry, not restated, so a contract cannot ship undeclared.

Neither `compute_cascade` nor `check_dimension` raises. Every refusal comes back as a typed
result with diagnostics.

The package ships a PEP 561 marker, so a consumer type-checks against these contracts rather than
importing `Any`. Without it the frozen models, the `Literal[False]` that makes a partial result
unrepresentable, and the annotation that refuses a `float` amount would all stop at the import.

## Cost cascade

```python
from motor_costos import CostCascadeV1, compute_cascade

result = compute_cascade(CostCascadeV1(categories=..., labour_category=..., lines=..., factors=...))
```

The contract is `cost-cascade.v1`. It returns `success`, the `currency` the composition is
expressed in, a `cost` per declared category, twelve named `stages` in cascade order, and the
final `unit_cost`. `success` says the computation completed; a composition can complete and still
carry warnings.

The stages, in order, are `total_resources`, `tool_cost`, `safety_cost`, `direct_cost`,
`indirect_cost`, `subtotal_1`, `financing_cost`, `subtotal_2`, `utility`, `subtotal_3`, `tax`,
`unit_cost`. Each percentage applies to the running subtotal, which already includes every prior
markup. Tool wear and safety equipment are the exception: they are percentages of the declared
labour category and belong to direct cost, before the compounding begins.

Before any of that, each line resolves to `quantity * unit_price * (1 + waste_pct / 100)`. That
stage is the engine's, not the caller's — it is where the waste factor is applied, and a caller
who supplied a pre-computed line total could apply it twice.

The category taxonomy and the labour category are **declared by the caller**, and every declared
category appears in the breakdown. The sum of the per-category figures plus the two surcharges
equals the direct cost, and the engine asserts that as an output invariant (ADR 0003).

The fixed limits are 10,000 resource lines, 64 declared categories, 10 integer digits of monetary
magnitude, 100 characters per identifier, 1,000 characters per diagnostic string, and 1,000
diagnostics per result. A nesting depth of 1: an APU cannot contain another APU, and the engine
declares that rather than half-supporting it. Exceeding any limit fails the whole computation —
`truncated` is typed `Literal[False]`, so a partial result is not representable.

The monetary magnitude bounds each unit price, **each line total**, and each cascade stage. The
middle one carries the weight: `quantity` has no ceiling of its own, so bounding the line total is
what keeps every later stage quantisable — 10,000 lines below the ceiling, times the most the
cascade can compound, still fits inside the engine's 28 digits. A line over it names the line, not
a downstream stage, because the line is where a caller can act.

The sidecar method is `cost.cascade.v1` with exactly the fields of `CostCascadeV1`.

## Rounding

```python
from motor_costos import RoundingPolicy

RoundingPolicy(mode="final", money_scale=4)   # the default
```

The policy is an input, never a hidden constant. Three modes: `exact` never quantises,
`final` keeps intermediates exact and quantises the unit cost, `per-stage` quantises every stage
before it feeds the next. `ROUND_HALF_UP` is the only rounding mode, and it is the one the domain
already pinned with ties that banker's rounding resolves the other way.

All arithmetic runs inside an explicit `decimal.localcontext()` at 28 significant digits. The
caller's global decimal context cannot move the answer, and that ceiling is also what bounds
intermediate growth in `exact` mode.

Amounts are given as a string or an integer. A `float` is refused, in-process and on the wire: a
monetary value that arrives as an IEEE double has already lost precision. Result amounts
serialise as strings for the same reason.

Stage values keep the exponent the arithmetic itself produces, trailing zeros and all —
`subtotal_3` is `37.0137600000`, not `37.01376`. Renormalising would silently change what a
consumer receives, so the engine does not. Compare numerically.

See ADR 0001 for the evidence behind the default.

## Dimensional compatibility

```python
from motor_costos import DimensionCheckV1, check_dimension

result = check_dimension(DimensionCheckV1(quantity_field="volume", unit_category="length"))
```

The contract is `dimension-check.v1`. It returns whether the pairing is `compatible`, whether the
unit category is `satisfiable` at all, and the `expected_field` for that unit — so a rejection
names the fix.

The correspondence is `area→area`, `volume→volume`, `length→length`, `count→unit`,
`weight→weight`, and the inverse is derived by inverting it. `time`, `capacity` and `other` are
deliberately outside it: an APU priced in hours, gallons or "global" measures no physical
dimension, so no quantity can ever satisfy it.

`unit_category` is required and authoritative; the engine never infers it. `unit_symbol` is
optional — when given it is folded (`M2`, `m²` and ` M. 2 ` all fold to `m2`) and cross-checked
against a 67-token vocabulary. A symbol that contradicts its declared category, or that the
vocabulary does not know, produces a warning; neither is resolved silently.

No unit library. See ADR 0002 for why `pint` was evaluated and declined.

The sidecar method is `dimension.check.v1` with exactly `{"quantity_field": ..., "unit_category":
..., "unit_symbol": ...}`, the last optional.

## Safety boundary

- The engine opens no file, no socket and no database. `publication` is typed `Literal["none"]`.
- A diagnostic has **no field** for a filesystem path, an exception or a stack trace. Leaking one
  is structurally impossible, not merely avoided.
- Every message and suggested action is a static literal. Caller data reaches a result only
  through typed context fields, which are length-bounded.
- Third-party exception text never crosses the boundary. A pydantic validation failure is
  reported as a count and the field paths, never its wording.
- The JSON-RPC line limit is 1,000,000 bytes, and it bounds the sidecar's memory rather than only
  its answers: the reader refuses an oversized line without ever assembling one, then
  resynchronises to the next newline so the tail is not read as further requests. `NaN` and
  `Infinity` are rejected at any depth, by the parser and again by the models.
- A boolean JSON-RPC id is refused, because in Python it would silently correlate with `1`.
- A domain refusal is a `result` with diagnostics, not a JSON-RPC `error`. The call worked; the
  composition did not.

## Determinism

The same input produces the same result, byte for byte, in any process and on any platform.
Diagnostic context is flattened to a sorted tuple, schemas are rendered with sorted keys, and
arithmetic runs at a pinned precision inside an isolated decimal context.

## Testing

Beyond the known-answer oracles, the suite applies **18 mutants to the bytes** of `cascade.py`
and `rounding.py`, each of which must be killed by a **named** test — plus a control proving the
harness passes unmutated, and a guard that fails loudly if a mutation anchor stops matching the
source. A test that cannot fail for the reason it states is not a test.

`tests/test_publication_hygiene.py` additionally scans every published file for internal
references, so the separation between what is public and what is not is enforced on every run
rather than being a one-time cleanup.

CI gates on `ruff check` before the suite. The rule selection is argued in `pyproject.toml` rather
than copied: `S` and `BLE` are there because the safety boundary above is a written claim, and the
handful of suppressions each carry their reason inline. `RUF100` is what keeps that list honest —
a `# noqa` that stops being necessary fails the build instead of becoming decoration.

## Provenance and decisions

Domain knowledge was translated, not copied, from a prior in-house implementation. See
[`docs/PROVENANCE.md`](docs/PROVENANCE.md) and [`docs/adr/`](docs/adr/) — three decisions:
the rounding policy, the choice against a units library, and the parametrised taxonomy.

## License

Apache License 2.0 — see [`LICENSE`](LICENSE). Copyright 2026 MAMUT.

Domain knowledge was translated, never copied, from private MAMUT
applications; those repositories are not covered by this license and nothing
was committed back to them. See `docs/PROVENANCE.md`.
