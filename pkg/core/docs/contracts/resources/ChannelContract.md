# Channel

Status: Enforced

## Purpose

This document provides an overview of all Channel domain testing contracts. Individual Channel operations are covered by specific behavioral contracts that define exact CLI syntax, safety expectations, and data effects.

---

## Scope

The Channel domain is covered by the following specific contracts:

- **[Channel Add](ChannelAddContract.md)**: Creating new channels
- **[Channel Update](ChannelUpdateContract.md)**: Updating channel configuration/state
- **[Channel List](ChannelListContract.md)**: Listing channels
- **[Channel Show](ChannelShowContract.md)**: Displaying a channel
- **[Channel Delete](ChannelDeleteContract.md)**: Deleting channels (guarded by dependency checks)
- **[Channel Validate](ChannelValidateContract.md)**: Non-mutating validation/dry-run of channel invariants

---

## Contract Structure

Each Channel operation follows the standard contract pattern:

1. **Command Shape**: Exact CLI syntax and required flags
2. **Safety Expectations**: Confirmation prompts, dry-run behavior (where applicable)
3. **Output Format**: Human-readable and JSON output structure
4. **Exit Codes**: Success and failure exit codes
5. **Data Effects**: What changes in the database
6. **Behavior Contract Rules (B-#)**: Operator-facing behavior guarantees
7. **Data Contract Rules (D-#)**: Persistence, lifecycle, and integrity guarantees
8. **Test Coverage Mapping**: Explicit mapping from rule IDs to test files

---

## Design Principles

- **Safety first:** No destructive operation runs against live data during automated tests
- **One contract per noun/verb:** Each Channel operation has its own focused contract
- **Mock-first validation:** All operations must first be tested using mock/test databases
- **Idempotent where appropriate:** `list`/`show` are read-only and repeatable; `add`/`update` are deterministic with explicit validation and optimistic locking
- **Clear error handling:** Failed operations provide actionable diagnostics
- **Unit of Work:** All database-modifying operations are wrapped in atomic transactions
- **Optimistic locking:** Updates require a version precondition and fail on conflict
- **Effective-dated changes:** `programming_day_start` edits MAY be effective-dated and trigger rebuilds (no retro reinterpretation)

---

## Common Safety Patterns

### Test Database Usage

- `--test-db` flag directs operations to an isolated test environment
- Test database must be completely isolated from production
- No test data should persist between test sessions

### Dry-run Support

- Where applicable (e.g., destructive or wide-impact updates), a `--dry-run` mode SHOULD preview the intended changes without committing

### Confirmation Models

- Destructive operations (e.g., delete) require confirmation prompts
- `--yes` flag skips confirmations in non-interactive contexts
- See [_ops/DestructiveOperationConfirmation.md](../_ops/DestructiveOperationConfirmation.md)

### Pagination Guidance

- `channel list` SHOULD support pagination to prevent unbounded responses in large deployments

### Effective-Dated Mutations

- `programming_day_start` changes MAY specify an `effective_date` and trigger horizon/EPG rebuilds from that date forward

### Optimistic Locking

- `update` MUST include a `version` precondition; server increments by 1 on success (source of truth may be DB trigger or application layer)

---

## Validation Scope & Triggers

- Validate on `add`, `update`, and via explicit `retrovue channel validate`.
- Always validate the Channel row.
- Cross-validate `SchedulePlan`/`ScheduleDay` alignment:
  - On demand via `validate` command, and
  - On `update` when `--effective-date` is provided for changes that impact alignment.
- On such updates, return `impacted_entities` (IDs and counts). Do not auto-rebuild; report only.

## Calendar Policy

- Interpret inputs/outputs in local time; store timestamps in UTC.
- Never assume 60-minute hours during DST; schedule math is block-based.

## Observability & Ops

- Emit `channel.validation.failed` with payload `{channel_id, codes:{by_code,count}, totals:{violations,warnings}}`.
- Validator does not rebuild; separate job or update flow initiates rebuilds.

## IDs

- Validator and CLI use Channel integer `id`. Internal UUIDs never surface.

---

## Channel-Specific Guardrails

- Slug: lowercase kebab-case, unique, immutable; title ≤ 120 chars, slug ≤ 64 chars
- Grid: `grid_block_minutes ∈ {15,30,60}`
- Offsets: integers 0–59, sorted, unique; every `offset % grid == 0`; 1–6 entries; same set repeats each hour
- Programming day start: minute aligns to grid and is in offsets; seconds `== 00`
- Active/archive: `is_active=false` excludes prospectively; historical rows retained
- Revalidation: grid/offset changes require revalidation; mark `SchedulePlan`/`ScheduleDay` as needs-review
- Delete gate: no dependents (plans, days, EPG rows, playout configs, broadcast bindings, ad/avail policies)
- Backfill: when activating, backfill horizons/EPG for the standard window
- Lints (non-fatal): warn if grid=60 with non-zero offsets; warn on sparse/nonstandard offset sets

---

## Contract Test Requirements

Each Channel contract should have exactly two test files:

1. **CLI Contract Test**: `tests/contracts/test_channel_{verb}_contract.py`

   - CLI syntax validation
   - Flag behavior verification
   - Output format validation
   - Error message handling

2. **Data Contract Test**: `tests/contracts/test_channel_{verb}_data_contract.py`

   - Database state changes
   - Transaction boundaries
   - Data integrity verification
   - Side effects validation

---

## Channel Lifecycle

1. **Creation**: Channel is created with grid, offsets, and anchor
2. **Configuration**: Templates/days aligned and validated against channel invariants
3. **Horizon/EPG**: Generated and maintained using channel scheduling parameters
4. **Archival**: `is_active=false` excludes channel from future generations (historical rows retained)
5. **Deletion**: Only allowed with no dependencies (templates, days, EPG rows, playout configs, broadcast bindings, ad/avail policies)

---

## See Also

- [Channel Domain Documentation](../../domain/Channel.md) - Core domain model and rules
- [CLI Contract](README.md) - General CLI command standards
- [Unit of Work](../_ops/UnitOfWorkContract.md) - Transaction management requirements
- [_ops/DestructiveOperationConfirmation.md](../_ops/DestructiveOperationConfirmation.md) - Safe destructive operation pattern


