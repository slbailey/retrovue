# INV-DURATION-EXTRACTION-NORMALIZATION-001 — Duration extraction normalizes ffprobe sources before failure

Status: Invariant
Authority Level: Planning
Derived From: `LAW-ELIGIBILITY`, `LAW-DERIVATION`

## Purpose

ffprobe duration metadata is container-dependent and may appear in different fields for equally valid media. Duration extraction MUST normalize these source variants before declaring failure so valid assets are not misclassified as invalid.

## Guarantee

Duration extraction MUST attempt ffprobe duration sources in this priority order before declaring duration failure:
1. `format.duration`
2. `max(stream.duration)`
3. `stream.tags.DURATION` parsed from `HH:MM:SS[.fraction]`

`duration_ms` MUST be derived from the first valid source found. `invalid_duration=True` MUST be set only if all sources fail to yield a strictly positive duration.

This invariant does NOT relax `INV-ASSET-DURATION-REQUIRED-FOR-READY-001`. Assets still MUST have `duration_ms > 0` to become `ready`.

## Preconditions

- ffprobe payload is available from the duration/probe enricher execution.
- Normalization executes inside ingest enrichment before readiness evaluation.

## Observability

When normalization fails, enrichment MUST emit structured diagnostics including checked probe paths and a machine-readable failure reason. Assets that fail normalization remain non-ready with invalid duration status.

## Deterministic Testability

1. Provide ffprobe fixture with valid `format.duration` and invalid stream values; assert valid `duration_ms` from `format.duration`.
2. Provide fixture with missing format duration and multiple valid stream durations; assert `duration_ms` from max stream duration.
3. Provide fixture with only `stream.tags.DURATION`; assert parsed `duration_ms`.
4. Provide fixture with no valid values across all sources; assert invalid duration outcome.

## Failure Semantics

**Enrichment fault.** Duration normalization cannot produce a strictly positive duration after exhausting all required sources. Typical failure modes include:
- missing `format.duration`
- `stream.duration` values missing, `N/A`, or non-numeric
- malformed `stream.tags.DURATION`
- extracted duration is zero or negative

## Implementation Notes

- Prefer container-level duration (`format.duration`) when valid.
- Fallback sequence MUST be deterministic and MUST follow declared priority.
- If multiple stream durations are available and `format.duration` is unavailable, choose max stream duration.
- `stream.tags.DURATION` parsing MUST support `HH:MM:SS` with optional fractional seconds.
- Conversion to `duration_ms` MUST use consistent millisecond precision rounding.
- Zero or negative durations are invalid.
- No downstream component may re-probe or recompute duration.

## Examples

- MKV with `format.duration` present and `stream.duration=N/A` -> valid (`format.duration` used).
- File with only `TAG:DURATION`/`stream.tags.DURATION` -> valid (tag parsed).
- File with no valid duration in any source -> invalid.

## Required Tests

- `server/tests/contracts/ingest/test_inv_duration_extraction_normalization.py`

## Enforcement Evidence

TODO

