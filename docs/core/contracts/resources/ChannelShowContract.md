## Channel Show Contract

## Purpose

Define the behavioral contract for showing a single broadcast channel.

---

## Command Shape

```
retrovue channel show <uuid-or-slug> [--json] [--test-db]
retrovue channel show --id <uuid-or-slug> [--json] [--test-db]
```

### Parameters

- `<uuid-or-slug>` (positional) or `--id <uuid-or-slug>`: Channel identifier.
- `--json` (optional): Machine-readable output.
- `--test-db` (optional): Use isolated test database session.

---

## Output Format

### Human-Readable

```
Channel:
  ID: 7
  Name: RetroToons
  Grid Size (min): 30
  Grid Offset (min): 0
  Broadcast day start: 06:00
  Active: true
  Created: 2025-01-01 12:00:00
  Updated: -
```

### JSON

```json
{
  "status": "ok",
  "channel": {
    "id": 7,
    "name": "RetroToons",
    "grid_size_minutes": 30,
    "grid_offset_minutes": 0,
    "broadcast_day_start": "06:00",
    "is_active": true,
    "created_at": "2025-01-01T12:00:00Z",
    "updated_at": null
  }
}
```

---

## Exit Codes

- `0`: Channel found and displayed.
- `1`: Channel not found, DB failure, or `--test-db` session unavailable.

---

## Behavior Contract Rules (B-#)

- **B-1:** Identifier (UUID or slug) MUST resolve to an existing channel; else exit 1 with error.
- **B-2:** `--json` returns valid JSON with a `channel` object.
- **B-3:** Output deterministic and complete for the defined fields.
- **B-4:** Read-only; no mutations.
- **B-5:** `--test-db` maintains identical shape/exit codes.

---

## Data Contract Rules (D-#)

- **D-1:** Reflects the persisted row exactly.
- **D-2:** Timestamps reported in UTC.
- **D-3:** Test DB isolation preserved.

---

## Tests

Planned tests:

- tests/contracts/test_channel_show_contract.py::test_channel_show__help_flag
- tests/contracts/test_channel_show_contract.py::test_channel_show__success_human
- tests/contracts/test_channel_show_contract.py::test_channel_show__success_json
- tests/contracts/test_channel_show_contract.py::test_channel_show__not_found
- tests/contracts/test_channel_show_contract.py::test_channel_show__test_db_isolation

---

## See also

- [Channel List](ChannelListContract.md)
- [Channel](../../domain/Channel.md)

