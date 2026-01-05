## Channel List Contract

## Purpose

Define the behavioral contract for listing broadcast channels.

---

## Command Shape

```
retrovue channel list [--json] [--test-db]
```

### Parameters

- `--json` (optional): Machine-readable output.
- `--test-db` (optional): Use isolated test database session.
 

---

## Safety Expectations

- Read-only, idempotent, production safe.
- No external system calls.
- `--test-db` MUST isolate from production.

---

## Output Format

### Human-Readable

```
Channels:
  ID: 7
  Name: RetroToons
  Grid Size (min): 30
  Grid Offset (min): 0
  Broadcast day start: 06:00
  Active: true

Total: 1 channels
```

### JSON

```json
{
  "status": "ok",
  "total": 1,
  "channels": [
    {
      "id": 7,
      "name": "RetroToons",
      "grid_size_minutes": 30,
      "grid_offset_minutes": 0,
      "broadcast_day_start": "06:00",
      "is_active": true,
      "created_at": "2025-01-01T12:00:00Z",
      "updated_at": null
    }
  ]
}
```

---

## Exit Codes

- `0`: Command succeeded (including zero results).
- `1`: DB failure or `--test-db` session unavailable.

---

## Behavior Contract Rules (B-#)

- **B-1:** Returns all persisted channels.
- **B-2:** `--json` returns valid JSON with `status`, `total`, `channels`.
- **B-3:** Output deterministic; sorted by name (case-insensitive), then id ascending.
- **B-4:** Read-only; no mutations.
- **B-5:** `--test-db` maintains identical shape/exit codes.
 

---

## Data Contract Rules (D-#)

- **D-1:** Reflects `channels` rows at query time.
- **D-2:** Includes correct latest metadata fields.
- **D-3:** No fabricated data; derived fields computed from stored values only.
- **D-4:** Test DB isolation preserved.
- **D-5:** `total` reflects number of rows returned.

---

## Tests

Planned tests:

- tests/contracts/test_channel_list_contract.py::test_channel_list__help_flag
- tests/contracts/test_channel_list_contract.py::test_channel_list__lists_all_human
- tests/contracts/test_channel_list_contract.py::test_channel_list__lists_all_json
- tests/contracts/test_channel_list_contract.py::test_channel_list__deterministic_sort
- tests/contracts/test_channel_list_contract.py::test_channel_list__test_db_isolation

---

## See also

- [Channel Show](ChannelShowContract.md)
- [Channel](../../domain/Channel.md)

