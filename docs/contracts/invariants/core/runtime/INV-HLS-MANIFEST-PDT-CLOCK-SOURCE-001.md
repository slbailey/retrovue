# INV-HLS-MANIFEST-PDT-CLOCK-SOURCE-001

## Behavioral Guarantee

The `EXT-X-PROGRAM-DATE-TIME` value in the manifest is derived exclusively from the segment's stored `wall_clock_start_utc_ms` field, which itself originates from BlockPlan timing. The manifest generator MUST NOT call any system clock function to produce this value.

## Authority Model

ManifestGenerator owns PDT formatting. Segment `wall_clock_start_utc_ms` is the sole input. `INV-HLS-SEGMENT-WALLCLOCK-001` guarantees the upstream value is MasterClock-derived.

## Boundary / Constraint

- The PDT value MUST be formatted from `segment.wall_clock_start_utc_ms` and no other source.
- The generator MUST NOT import or call `datetime.now()`, `time.time()`, `time.monotonic()`, or any system clock function in the PDT code path.
- The formatted timestamp MUST use ISO 8601 with UTC timezone designator (Z suffix) and millisecond precision.

## Violation

PDT value derived from system clock; generator calling time functions in PDT path; timestamp not in ISO 8601 UTC format.

## Derives From

`INV-HLS-MANIFEST-PDT-001`, `INV-HLS-SEGMENT-WALLCLOCK-001`, `LAW-CLOCK`

## Required Tests

- `pkg/core/tests/contracts/runtime/test_inv_hls_manifest_consistency.py`

## Enforcement Evidence

TODO
