## Channel Delete Contract

## Purpose

Define the behavioral contract for deleting an existing broadcast channel.

---

## Command Shape

```
retrovue channel delete <uuid-or-slug> [--yes] [--test-db]
retrovue channel delete --id <uuid-or-slug> [--yes] [--test-db]
```

### Parameters

- `<uuid-or-slug>` (positional) or `--id <uuid-or-slug>`: Channel identifier; accepts UUID or slug.
- `--yes` (optional): Non-interactive confirmation for destructive action.
- `--test-db` (optional): Use isolated test database session.

---

## Safety Expectations

- Destructive operation confirmation MUST follow [_ops/DestructiveOperationConfirmation.md].
- MUST refuse deletion if dependencies exist (e.g., schedule days) with actionable error.
- `--test-db` MUST isolate from production.

---

## Output

### Human-Readable

```
Channel deleted: hbo
```

### JSON

```json
{ "status": "ok", "deleted": 1, "id": 7 }
```

---

## Exit Codes

- `0`: Channel deleted.
- `1`: Not found, dependencies prevent deletion, confirmation refused, DB failure, or `--test-db` session unavailable.

---

## Behavior Contract Rules (B-#)

- **B-1:** `--id` MUST resolve to an existing channel by UUID or slug; else exit 1.
- **B-2:** If dependencies exist, MUST exit 1 with guidance to archive (`--inactive`) instead.
- **B-3:** Without `--yes`, MUST prompt; tests run non-interactively MUST pass `--yes`.
- **B-4:** JSON mode returns `{status, deleted, id}`.
- **B-5:** `--test-db` maintains identical shape/exit codes.
-- **B-6:** When blocked by dependencies, output MUST explicitly suggest `retrovue channel update --id <id> --inactive` as a safer alternative.

---

## Data Contract Rules (D-#)

- **D-1:** One row removed from `channels` when successful.
- **D-2:** No orphaned references remain.
- **D-3:** Test DB isolation preserved.

---

## Tests

Planned tests:

- tests/contracts/test_channel_delete_contract.py::test_channel_delete__help_flag
- tests/contracts/test_channel_delete_contract.py::test_channel_delete__requires_yes
- tests/contracts/test_channel_delete_contract.py::test_channel_delete__success
- tests/contracts/test_channel_delete_contract.py::test_channel_delete__not_found
- tests/contracts/test_channel_delete_contract.py::test_channel_delete__blocked_by_dependencies
- tests/contracts/test_channel_delete_contract.py::test_channel_delete__test_db_isolation

---

## See also

- [_ops/DestructiveOperationConfirmation.md](../_ops/DestructiveOperationConfirmation.md)
- [Channel Update](ChannelUpdateContract.md)
- [Channel](../../domain/Channel.md)

