# INV-ASSET-PROBE-ONLY-FIELD-AUTHORITY-001 — Probe-only fields cannot be authoritative

Status: Invariant
Authority Level: Planning
Derived From: `LAW-DERIVATION`

## Purpose

Probe-only fields (`runtime_seconds`, `resolution`, `aspect_ratio`, `audio_channels`, `audio_format`, `container`, `video_codec`) are derived from the media file by ffprobe and MUST NOT be declared as operator truth in sidecar `authoritative_fields`. Allowing operators to override probe-derived values would create conflicting sources of truth for technical metadata consumed by the planning pipeline.

## Guarantee

Sidecar `meta.authoritative_fields` MUST NOT contain any probe-only field. Validation MUST reject any sidecar whose `authoritative_fields` list intersects with the `PROBE_ONLY_FIELDS` set.

## Preconditions

None. This invariant holds unconditionally for all sidecar validation.

## Observability

Enforced in `BaseRetroVueSidecar.model_validate()` in `metadata_schema.py`. Validation raises `ValueError` listing the offending probe-only fields.

## Deterministic Testability

Construct a sidecar dict with `meta.authoritative_fields` containing a probe-only field (e.g., `runtime_seconds`). Assert `model_validate()` raises `ValueError`. Construct a sidecar without probe-only fields in `authoritative_fields` and assert validation succeeds. No real files required.

## Failure Semantics

**Schema violation.** The sidecar YAML declares probe-derived fields as operator truth. The sidecar MUST be corrected before import.

## Required Tests

- `pkg/core/tests/contracts/test_asset_invariants.py::TestInvAssetProbeOnlyFieldAuthority001`

## Enforcement Evidence

- `pkg/core/src/retrovue/domain/metadata_schema.py` — `PROBE_ONLY_FIELDS` tuple and `BaseRetroVueSidecar.model_validate()` intersection check
- Error tag: `INV-ASSET-PROBE-ONLY-FIELD-AUTHORITY-001-VIOLATED`
