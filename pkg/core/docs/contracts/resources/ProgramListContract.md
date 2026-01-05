# Program List Contract

_Related: [ProgramContract](ProgramContract.md) • [Domain: Program](../../domain/Program.md) • [Domain: SchedulePlan](../../domain/SchedulePlan.md)_

## Purpose

This contract defines the behavior of the `retrovue channel plan <channel> <plan> program list` command, which lists all programs in a schedule plan.

## Command Syntax

```bash
retrovue channel plan <channel> <plan> program list [--json] [--test-db]
```

## Required Arguments

- `<channel>` - Channel identifier (UUID or slug)
- `<plan>` - Plan identifier (UUID or name)

## Optional Options

- `--json` - Output in JSON format
- `--test-db` - Use test database context

## Contract Rules

### PL-1: Channel and Plan Resolution

**Rule:** The command MUST resolve the channel and plan by their identifiers before listing programs.

**Behavior:**
- If channel is not found → exit 1, error message: "Error: Channel '<identifier>' not found"
- If plan is not found → exit 1, error message: "Error: Plan '<identifier>' not found"
- If plan does not belong to channel → exit 1, error message: "Error: Plan '<plan>' does not belong to channel '<channel>'"

### PL-2: Program Ordering

**Rule:** Programs MUST be listed in ascending order by start_time.

**Behavior:**
- Programs sorted by start_time (00:00 to 24:00)
- Programs with same start_time sorted by creation time

### PL-3: Empty Plan Handling

**Rule:** If plan has no programs, the command MUST return empty list (not an error).

**Behavior:**
- Exit code: 0
- Output shows empty list or "No programs found" message

## Success Behavior

On successful listing:

**Exit Code:** 0

**Output (non-JSON, no programs):**
```
No programs found
```

**Output (non-JSON, with programs):**
```
Programs:
  ID: <program-id-1>
  Start: <start-time-1>
  Duration: <duration-1> minutes
  Content Type: <content-type-1>
  Content Reference: <content-ref-1>
  
  ID: <program-id-2>
  Start: <start-time-2>
  Duration: <duration-2> minutes
  Content Type: <content-type-2>
  Content Reference: <content-ref-2>
  
Total: <count> programs
```

**Output (JSON):**
```json
{
  "status": "ok",
  "total": <count>,
  "programs": [
    {
      "id": "<program-id>",
      "plan_id": "<plan-id>",
      "channel_id": "<channel-id>",
      "start_time": "<start-time>",
      "duration": <duration>,
      "content_type": "<content-type>",
      "content_ref": "<content-ref>",
      "episode_policy": "<policy>",
      "label_id": "<label-id>",
      "operator_intent": "<intent>",
      "created_at": "<timestamp>",
      "updated_at": "<timestamp>"
    }
  ]
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

### Example 1: List Programs

```bash
retrovue channel plan abc xyz program list
```

**Expected:** List of all programs in plan xyz, sorted by start_time.

### Example 2: List Programs (JSON)

```bash
retrovue channel plan abc xyz program list --json
```

**Expected:** JSON output with programs array.

### Example 3: Empty Plan

```bash
retrovue channel plan abc xyz program list
```

**Expected (if plan has no programs):** "No programs found", exit 0.

## Test Coverage Requirements

Tests MUST verify:

1. Successful listing with programs
2. Empty plan handling
3. Program ordering by start_time
4. Channel and plan resolution (valid and invalid cases)
5. JSON output format
6. Error message clarity

## Related Contracts

- [ProgramContract](ProgramContract.md) - Program domain contract rules
- [ProgramAddContract](ProgramAddContract.md) - Program creation contract

