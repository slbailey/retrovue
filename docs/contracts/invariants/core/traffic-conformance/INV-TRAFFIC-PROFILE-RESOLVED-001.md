# INV-TRAFFIC-PROFILE-RESOLVED-001 — Traffic profile resolution for every break-bearing block

Status: Invariant
Authority Level: Planning
Derived From: `LAW-CONTENT-AUTHORITY`, `LAW-DERIVATION`

## Purpose

Every block with breaks MUST have a resolved traffic profile so TrafficManager can select fill assets deterministically. Without a resolved profile, TrafficManager would have to infer policy from content type — violating `LAW-CONTENT-AUTHORITY` (DSL is sole editorial authority) and `LAW-DERIVATION` (artifact chain traceability).

## Guarantee

Every compiled block that contains break structures MUST carry a resolved traffic profile name. Resolution precedence: block-level override > template `breaks.traffic_profile` > channel `traffic.default`. An unresolvable profile reference MUST fail at YAML validation time. TrafficManager MUST NOT infer traffic policy from content type or template name.

## Preconditions

- Channel YAML declares `traffic.default` and `traffic.profiles`.
- Template (if referenced) is fully resolved including `extends`.

## Observability

- Validation failure: structured error identifying the unresolvable profile reference, the block, and the template.
- Resolved profile name is carried on each `BreakStructure` in the compiled block output.

## Deterministic Testability

Construct a block referencing a template with `traffic_profile: X`. Verify the compiled output carries `X` on all break structures. Remove the template profile and verify channel default is used. Remove channel default and verify validation fails.

## Failure Semantics

Planning fault. YAML validation error before compilation begins.

## Required Tests

- `pkg/core/tests/contracts/test_traffic_profiles_conformance.py`

## Enforcement Evidence

TODO
