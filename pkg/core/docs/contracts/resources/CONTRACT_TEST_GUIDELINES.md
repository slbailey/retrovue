# Retrovue Contract Test Guidelines

## Overview

All contract tests verify both **command behavior** and **data integrity** for Retrovue operations.

For every contract (e.g., `EnricherAddContract`, `ScheduleCreateContract`, `ChannelUpdateContract`), two tests must exist:

1. `<command>_contract.py`

   - Tests CLI or service-level behavior.
   - Ensures command executes as specified in the corresponding contract markdown.
   - Validates stdout/stderr, logs, and persisted side effects.

2. `<command>_data_contract.py`
   - Tests data-layer consistency.
   - Validates that database state matches the contract (columns, cascades, rollback behavior, immutables).

---

## Test Requirements

Each contract test must:

- Follow pytest conventions.
- Use existing testing utilities from `tests/util/`.
- Validate all required fields defined in the contract markdown.
- Roll back transactions if validation fails.
- Ensure entity retrievability through list or query commands.
- Never use fake mocks; minimal real ORM models should be created instead.

---

## Example Prompt Template (for Cursor)
