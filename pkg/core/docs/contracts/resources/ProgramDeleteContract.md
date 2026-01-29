# Program Delete Contract

_Related: [ProgramContract](ProgramContract.md) • [Domain: Program](../../domain/Program.md) • [Domain: SchedulePlan](../../domain/SchedulePlan.md) • [DestructiveOperationConfirmation](../DestructiveOperationConfirmation.md)_

## Purpose

This contract defines the behavior of the `retrovue channel plan <channel> <plan> program delete` command, which deletes a program from a schedule plan.

## Command Syntax

```bash
retrovue channel plan <channel> <plan> program delete <program-id> [--yes] [--json] [--test-db]
```

## Required Arguments

- `<channel>` - Channel identifier (UUID or slug)
- `<plan>` - Plan identifier (UUID or name)
- `<program-id>` - Program UUID to delete

## Required Options

- `--yes` - Confirm deletion (required for non-interactive use, per DestructiveOperationConfirmation contract)

## Optional Options

- `--json` - Output in JSON format
- `--test-db` - Use test database context

## Contract Rules

### PD-1: Confirmation Requirement

**Rule:** The command MUST require `--yes` confirmation before deletion (per DestructiveOperationConfirmation contract).

**Behavior:**
- If `--yes` not provided → exit 1, error: "Deletion requires --yes confirmation"
- If `--yes` provided → proceed with deletion

### PD-2: Channel and Plan Resolution

**Rule:** The command MUST resolve the channel and plan by their identifiers before deleting the program.

**Behavior:**
- If channel is not found → exit 1, error message: "Error: Channel '<identifier>' not found"
- If plan is not found → exit 1, error message: "Error: Plan '<identifier>' not found"
- If plan does not belong to channel → exit 1, error message: "Error: Plan '<plan>' does not belong to channel '<channel>'"

### PD-3: Program Resolution

**Rule:** The command MUST resolve the program by UUID and verify it belongs to the specified plan.

**Behavior:**
- If program UUID is invalid → exit 1, error: "Invalid program UUID: <program-id>"
- If program not found → exit 1, error: "Program '<program-id>' not found"
- If program does not belong to plan → exit 1, error: "Program '<program-id>' does not belong to plan '<plan>'"

### PD-4: Deletion Execution

**Rule:** The command MUST delete the program from the database.

**Behavior:**
- Program is deleted from `programs` table
- Foreign key constraints are respected (cascade rules apply)
- Transaction is committed on success

## Success Behavior

On successful deletion:

**Exit Code:** 0

**Output (non-JSON):**
```
Program deleted: <program-id>
```

**Output (JSON):**
```json
{
  "status": "ok",
  "deleted": 1,
  "id": "<program-id>"
}
```

## Error Behavior

On error:

**Exit Code:** 1

**Output (non-JSON):**
```
Error: <error-message>
```

**Output (JSON):**
```json
{
  "status": "error",
  "error": "<error-message>"
}
```

## Examples

### Example 1: Delete Program

```bash
retrovue channel plan abc xyz program delete 1234 --yes
```

**Expected:** Program deleted, exit 0.

### Example 2: Delete Program (JSON)

```bash
retrovue channel plan abc xyz program delete 1234 --yes --json
```

**Expected:** JSON output confirming deletion.

### Example 3: Missing Confirmation

```bash
retrovue channel plan abc xyz program delete 1234
```

**Expected:** Exit 1, error: "Deletion requires --yes confirmation"

### Example 4: Program Not Found

```bash
retrovue channel plan abc xyz program delete 9999 --yes
```

**Expected:** Exit 1, error: "Program '9999' not found"

## Test Coverage Requirements

Tests MUST verify:

1. Successful deletion with confirmation
2. Confirmation requirement (missing --yes)
3. Channel and plan resolution (valid and invalid cases)
4. Program resolution (valid, invalid UUID, not found, wrong plan)
5. JSON output format
6. Error message clarity
7. Non-interactive mode (--yes required)

## Related Contracts

- [ProgramContract](ProgramContract.md) - Program domain contract rules
- [DestructiveOperationConfirmation](../DestructiveOperationConfirmation.md) - Confirmation requirements for destructive operations

