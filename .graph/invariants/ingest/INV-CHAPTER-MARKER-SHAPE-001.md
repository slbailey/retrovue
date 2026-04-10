# INV-CHAPTER-MARKER-SHAPE-001

**Domain:** ingest

## Plain-language rule

FFprobe enricher MUST store extracted chapter markers at `probed.chapter_markers` with shape `[{time_ms: int, title: str}]`. When no chapters exist, the key MUST be absent (not an empty list).

## Why it exists

Scheduling consumes `probed.chapter_markers` for break placement. A divergent shape or key name silently breaks the cross-domain contract.

## What it constrains

- **Service:** FFprobeEnricher — `_metadata_to_probed()` output shape.
- **Entity:** `asset-probed` — `payload.chapter_markers` field.

## Failure mode if violated

Schedule compiler skips or misplaces break points, producing incorrect ad break timing.
