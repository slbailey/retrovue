# INV-HLS-MANIFEST-SEQUENCE-MONOTONIC-001

## Behavioral Guarantee

The `EXT-X-MEDIA-SEQUENCE` value emitted by the manifest generator never decreases across successive generations for the same channel. The generator tracks the last emitted value and rejects any attempt to emit a lower one.

## Authority Model

ManifestGenerator owns sequence tracking. The last-emitted value is per-channel state within the generator.

## Boundary / Constraint

- Before emitting a manifest, the generator MUST verify `current_media_sequence >= last_emitted_media_sequence`.
- If the check fails, the generator MUST log at ERROR level with invariant ID and the expected vs. actual sequence values.
- On failure, the generator MUST clamp the value to `max(current, last_emitted)` and log the correction.
- The sequence tracker MUST reset only when the ChannelManager is destroyed (full channel teardown).

## Violation

`EXT-X-MEDIA-SEQUENCE` decreasing between successive manifest responses; sequence tracker not reset on teardown; clamping not applied on violation.

## Derives From

`INV-HLS-MANIFEST-SEQUENCE-001`, `LAW-CLOCK`

## Required Tests

- `pkg/core/tests/contracts/runtime/test_inv_hls_manifest_consistency.py`

## Enforcement Evidence

TODO
