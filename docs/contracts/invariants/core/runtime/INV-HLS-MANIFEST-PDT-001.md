# INV-HLS-MANIFEST-PDT-001

## Behavioral Guarantee

The HLS manifest contains `#EXT-X-PROGRAM-DATE-TIME` derived from the channel's MasterClock-based schedule, not from the server's system clock. This tag anchors the stream to wall-clock time.

## Authority Model

ManifestGenerator owns tag emission. Segment wall-clock timestamps (from `INV-HLS-SEGMENT-WALLCLOCK-001`) are the upstream authority.

## Boundary / Constraint

- The manifest MUST contain at least one `#EXT-X-PROGRAM-DATE-TIME` tag, immediately before the first segment entry.
- The tag value MUST be the wall-clock start timestamp of that segment, formatted as ISO 8601 with UTC timezone designator (Z suffix).
- The timestamp MUST originate from BlockPlan timing (MasterClock-derived), not from the server's system clock at manifest generation time.
- Each segment entry MUST be preceded by an `#EXTINF` tag whose value matches the segment's actual presentation duration.

## Violation

Missing `EXT-X-PROGRAM-DATE-TIME`; timestamp derived from system clock rather than MasterClock; `EXTINF` duration not matching segment's stored duration metadata.

## Derives From

`LAW-CLOCK`, `LAW-DERIVATION`

## Required Tests

- `server/tests/contracts/runtime/test_inv_hls_manifest.py`

## Enforcement Evidence

TODO
