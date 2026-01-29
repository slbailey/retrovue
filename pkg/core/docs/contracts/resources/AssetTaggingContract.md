# Asset Tagging Contract

## Purpose

Define the operator interface and data guarantees for tagging assets. Tagging is a
core capability used for organization, bulk operations, and selection.

---

## Command Shape

The CLI MUST support tagging via the update surface with a concise syntax:

```
retrovue asset update <asset_id> --tags "tag1,tag2,tag3" [--dry-run] [--json] [--test-db]
```

- `<asset_id>`: UUID, external ID (e.g., `plex-12345`), or canonical URI path
- `--tags` value: comma-separated list, spaces optional

Rationale: Reuses the update surface and keeps a short, frequent path.

Future extension (bulk verb) MAY be added later:

```
# Not required now; documented for future evolution
retrovue assets tag --add "tag1,tag2" --select <filters>
```

---

## Parameters

- `--tags` (required): Desired final tag set to assign to the asset.
  - Replaces the entire tag set by default (see Behavior B-3, B-4).
- `--dry-run`: Preview without persisting.
- `--json`: JSON output.
- `--test-db`: Isolated test database.

---

## Behavior Contract Rules (B-#)

- B-1: Tags are normalized: trim whitespace, collapse internal whitespace, lower-case.
- B-2: Duplicate tags after normalization are deduplicated; ordering is not significant.
- B-3: Default semantics are REPLACE: the resulting tag set equals the provided list.
- B-4: If either `--add-tags` or `--remove-tags` flags are introduced later,
       they MUST compose deterministically with REPLACE semantics; until then, only REPLACE
       is supported by `--tags`.
- B-5: Operation is idempotent: applying the same normalized set yields no changes
       on subsequent runs and exits 0.
- B-6: Human output MUST show: asset identifier, previous tags, resulting tags, and whether
       a change occurred.
- B-7: With `--json`, output MUST include keys: `status`, `asset_uuid`,
       `changes.tags.old`, `changes.tags.new`.
- B-8: On `--dry-run`, no writes occur; output MUST still show old/new sets.

---

## Data Contract Rules (D-#)

- D-1: Tags are stored in a normalized association (e.g., `asset_tags` join table) and
       are unique per asset after normalization.
- D-2: Tag normalization is enforced on write; persisted values are normalized forms.
- D-3: Updates occur in a single Unit of Work. Partial failures MUST roll back.
- D-4: Soft-deleted assets (`is_deleted=true`) MUST reject tagging with exit code 1.
- D-5: `retired` assets MAY be tagged; tagging does not alter lifecycle state.

---

## Exit Codes

- 0: Success (whether or not tags changed, assuming operation valid)
- 1: Validation error (asset not found, soft-deleted, invalid ID)

---

## Examples

```bash
# Replace tags with exactly these three
retrovue asset update 123e4567-e89b-12d3-a456-426614174000 --tags "classic, noir, 1940s"

# Preview changes
retrovue asset update plex-98765 --tags "kids,animation" --dry-run

# JSON output
retrovue asset update "/media/movies/Casablanca (1942).mkv" --tags "classic,drama" --json
```

---

## Test Coverage Mapping

- CLI: `tests/contracts/test_asset_tagging_contract.py`
  - Enforces B-1..B-8 and exit codes
- Data: `tests/contracts/test_asset_tagging_data_contract.py`
  - Enforces D-1..D-5 and transactionality

---

## See Also

- [Asset Contract](AssetContract.md)
- [Assets Select](AssetsSelectContract.md) — selecting assets for bulk tagging
- [Asset Update](AssetUpdateContract.md)


