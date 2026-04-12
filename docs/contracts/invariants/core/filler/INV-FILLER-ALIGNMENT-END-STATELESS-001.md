# INV-FILLER-ALIGNMENT-END-STATELESS-001 — End-aligned filler carries no state across gaps

Status: Invariant
Authority Level: Planning
Derived From: `LAW-DERIVATION`, `LAW-CONTENT-AUTHORITY`

## Purpose

End-aligned filler is defined to position the filler asset's ending at the block seam. This requires computing the offset independently for each gap. Carrying a wrapping offset from a prior gap would shift the endpoint, defeating the alignment guarantee. This protects `LAW-CONTENT-AUTHORITY` — the operator declared end alignment, meaning "hit EOF at the seam," and stateful offset accumulation would violate that intent.

## Guarantee

When `alignment` is `"end"`, each gap MUST be processed independently. The offset computation MUST NOT reuse, accumulate, or reference any wrapping offset from prior filler segments. The sole inputs to the computation are `gap_ms` and `filler_duration_ms`.

## Observability

Fill two consecutive gaps with `alignment="end"`. Verify the second gap's segments are identical regardless of the first gap's size. Vary the first gap's size and confirm the second gap's output is unchanged.

## Deterministic Testability

Invoke filler construction for two gaps in sequence with `alignment="end"`. Vary the first gap (e.g., 10,000ms vs 50,000ms). Assert the second gap produces identical segments in both cases. No real-time waits required.

## Failure Semantics

**Planning fault.** State leaking between gaps in end-aligned mode indicates the construction logic is reusing the start-mode wrapping offset.

## Required Tests

- `server/tests/contracts/test_filler_alignment.py`

## Enforcement Evidence

TODO
