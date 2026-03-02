# INV-INGEST-PATH-SEGMENT-TAG-001

## Statement

When a filesystem source collection is configured with `tag_from_path_segments: true`,
every directory component on the path between the configured root path and the file's
immediate parent (inclusive) MUST be emitted as a normalized tag on the resulting asset.
No intermediate path component may be silently dropped.

Normalization: each component is stripped of leading/trailing whitespace, collapsed to
single internal spaces, and lowercased before emission.

The root directory itself MUST NOT be included as a tag. The file name MUST NOT be
included as a tag.

## Canonical Pattern

```python
def _infer_tags_from_path_segments(self, file_path: Path) -> list[str]:
    """Emit each dir component between root and file parent as tag:{component}."""
    resolved_roots = {Path(r).resolve() for r in self.root_paths}
    segments: list[str] = []
    current = file_path.resolve().parent
    while True:
        if current in resolved_roots or current == current.parent:
            break           # stop before root; root itself is NOT a tag
        segments.append(current.name)
        current = current.parent
    # segments are deepest-first; normalize each
    return [f"tag:{seg.strip().lower()}" for seg in segments]

# Example:
# root = /mnt/data/Intros
# file = /mnt/data/Intros/HBO/1982/intro.mp4
# → segments (deepest first): ["1982", "HBO"]
# → raw_labels: ["tag:1982", "tag:hbo"]
# → persisted tags: {"1982", "hbo"}
```

## Affected Components

- `pkg/core/src/retrovue/adapters/importers/filesystem_importer.py`
  — `tag_from_path_segments` config flag, `_infer_tags_from_path_segments()` method
- `pkg/core/src/retrovue/cli/commands/_ops/collection_ingest_service.py`
  — reads `tag:` prefixed labels from `raw_labels`, writes to `asset_tags`

## Failure Modes

- A root-path boundary detection bug causes the root dir name (e.g., "Intros") to be
  emitted as a tag, polluting all assets in the collection with a spurious tag.
- Off-by-one in the walk causes the deepest subdir (immediately above the file) to be
  dropped, silently losing the most specific tag.
- Missing normalization causes mixed-case duplicates (`"HBO"` and `"hbo"`) to coexist.

## Origin

Defined to support operator-controlled path-based tagging for interstitial collections
such as "Intros", where subdirectory structure encodes network and era metadata that
the operator wants queryable as flat tags.

## Test Coverage

- `pkg/core/tests/contracts/runtime/test_inv_ingest_path_segment_tag.py`
  - `TestRuleAllSegmentsEmitted` — 2-deep path yields exactly 2 tags
  - `TestRuleNoSegmentDropped` — 3-deep path yields exactly 3 tags
  - `TestRuleNormalization` — mixed-case/spaced dir name → lowercase tag
  - `TestRuleOnlyBetweenRootAndParent` — root and filename excluded
  - `TestRuleDisabledByDefault` — without flag, interstitial inference runs instead
