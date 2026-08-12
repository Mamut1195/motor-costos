# ADR 0003: Resource categories are declared by the caller, including which one bears the labour surcharge

**Status:** Accepted

## Context

The implementation this engine was translated from hardcodes six categories — material, labour,
equipment, transport, tooling and subcontract — as an application-level enumeration. Its cascade
reads five of them by name and computes two surcharges, tool wear and safety equipment, as
percentages of labour alone.

Two consequences follow from hardcoding, and both were visible there.

**The taxonomy is not universal.** Another country or trade will name, split or merge these
categories. An engine that owns the list cannot be reused without editing it, which contradicts
the premise that this engine belongs to no application.

**A category the cascade does not name becomes a silent contributor.** The running total sums
*every* line, but only the five named categories are read back out. A tooling line therefore
inflates the direct cost while appearing in no per-category figure, so this identity holds only
when no such line exists:

```
material + labour + equipment + transport + subcontract + tool + safety == direct_cost
```

Worse, the composition already charges for tooling through a percentage of labour, so a tooling
line and that surcharge can double-count the same cost with nothing signalling it. The module
documentation there disagrees with the code about this — it lists tooling among the summed
resources rather than as a derived percentage, and omits both surcharges from its statement of
the direct-cost formula. Only the calculator itself is correct, which is exactly how the gap
survived reading.

## Decision

The contract input declares the category set, and declares which category is the base of the
labour surcharges. There is no default set and no default labour category: an absent declaration
is a contract error, not an inferred value.

The result breaks down cost for **every** declared category, not a subset. The engine asserts the
reconciliation identity — the sum of the per-category figures plus the surcharges equals the
direct cost — as an output invariant, and reports a diagnostic if it does not hold.

The surcharges themselves stay generic: each is a percentage applied to the declared labour
category's subtotal, and both remain part of direct cost, before the compounding cascade begins.

## Contract boundary

The engine does not know what a material or a subcontract is; it knows that a composition has
categories, that costs accumulate per category, and that some declared category carries
percentage surcharges. That is the whole of the domain knowledge the cascade needs, and keeping
it parametric is what lets the same engine serve another trade without an edit.

Refusing to default the labour category is the same rule applied everywhere here: what the caller
did not declare is a contract error, never a silent assumption. Defaulting it would work for
exactly one application and fail quietly for every other, producing a plausible number computed
against the wrong base — the same failure shape that `dimension-check.v1` exists to prevent.

Emitting every declared category, rather than a fixed subset, is what closes the silent-
contributor gap. The engine cannot decide whether a tooling line and a tooling surcharge
double-count — that is a modelling decision belonging to whoever composed the APU — but it can
guarantee the caller sees both. The reconciliation invariant makes an unreported contributor
structurally impossible rather than merely unlikely.

## Rollback

Replace the declared category set with a module-level constant of the six categories above and
pin the labour category to a fixed value. `CostCascadeV1` loses two required fields, and
`tests/test_invariants.py::test_the_labour_category_must_be_declared` and the reconciliation
invariant test must be removed. The oracle tests continue to pass unchanged, because they declare
exactly that taxonomy.
