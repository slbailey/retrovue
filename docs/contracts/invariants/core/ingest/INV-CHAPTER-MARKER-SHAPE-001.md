# INV-CHAPTER-MARKER-SHAPE-001 — Chapter markers use canonical probed shape

Status: Invariant
Authority Level: Planning
Derived From: `LAW-DERIVATION`, `LAW-CONTENT-AUTHORITY`

## Purpose

Protects `LAW-DERIVATION` by ensuring chapter markers extracted during enrichment conform to a single, well-defined shape in the `probed` namespace. Scheduling consumes `probed.chapter_markers` for break placement; a divergent shape silently breaks the cross-domain contract.

## Guarantee

When the FFprobe enricher extracts chapter markers from source media, the result MUST be stored at key `chapter_markers` in the `probed` payload. Each entry MUST contain exactly `time_ms` (int, milliseconds from asset start) and `title` (string). If source media contains no chapter metadata, `chapter_markers` MUST be absent from the `probed` payload (not an empty list).

## Preconditions

- FFprobe enricher executes successfully on the target asset.
- Source media is a container format that may carry chapter atoms (Matroska, MP4, etc.).

## Observability

- `probed.chapter_markers` present and well-shaped on enriched assets that contain source chapter metadata.
- `probed.chapter_markers` absent on assets whose source media has no chapter metadata.
- Label `chapters:<N>` emitted when N > 0 chapters are extracted.

## Deterministic Testability

1. Provide ffprobe output containing 3 chapters with `start_time`, `end_time`, and `tags.title`.
2. Run FFprobeEnricher.enrich().
3. Assert `probed["chapter_markers"]` is a list of 3 dicts, each with keys `time_ms` (int) and `title` (str).
4. Assert `probed["chapter_markers"]` is absent when ffprobe output contains an empty chapters list.

## Failure Semantics

**Planning fault.** Malformed chapter markers cause the schedule compiler to skip or misplace break points, producing incorrect ad break timing.

## Required Tests

- `server/tests/contracts/ingest/test_inv_chapter_marker_shape.py`

## Enforcement Evidence

TODO
