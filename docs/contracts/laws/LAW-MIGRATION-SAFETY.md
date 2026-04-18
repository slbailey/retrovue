# LAW-MIGRATION-SAFETY

## Constitutional Principle

Migrations that retire, rename, split, merge, or reshape a component boundary MUST proceed in discrete, independently mergeable, independently revertible phases. Contracts precede code. Coverage is continuous. Deletion is terminal.

## Implications

- Every phase that changes an invariant's subject, attribution, or enforcement lands the updated contract document before the implementing code.
- For every load-bearing invariant affected by the migration, at least one non-skipped test asserts the invariant against its current attribution target at all times. Phase-to-phase gaps where no test enforces a migrating invariant are prohibited.
- When a component is being retired, split, or merged, new code stands up alongside the old. The old component's externally-observable surface remains stable until all callers have been redirected.
- A deprecated artifact MUST NOT be deleted until production callers are verifiably zero and contract tests are verifiably rewritten or formally retired. Deletion PRs include automated evidence of both conditions.
- Each phase MUST be revertible by git-revert of its single PR. The deletion phase is the point of no return and requires explicit confirmation.

## Violation

Any PR that changes a migrating invariant's subject, attribution, or enforcement without landing the contract update first; that deletes a deprecated artifact without automated caller-zero and test-rewrite evidence; or that leaves a migrating invariant with zero test coverage at a phase boundary.
