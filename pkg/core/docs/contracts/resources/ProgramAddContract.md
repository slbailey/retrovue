# Program Add Contract

_Related: [ProgramContract](ProgramContract.md) • [Domain: Program](../../domain/Program.md) • [Domain: SchedulePlan](../../domain/SchedulePlan.md)_

## Purpose

This contract defines the behavior of the `retrovue channel plan <channel> <plan> program add` command, which creates a new program in a schedule plan.

## Command Syntax

```bash
retrovue channel plan <channel> <plan> program add --start <time> --duration <minutes> [content-options] [options]
```

## Required Arguments

- `<channel>` - Channel identifier (UUID or slug)
- `<plan>` - Plan identifier (UUID or name)

## Required Options

- `--start <time>` - Start time in HH:MM format (schedule-time, relative to broadcast day)
- `--duration <minutes>` - Duration in minutes (positive integer)

## Content Type Options

Exactly one of the following must be specified:

- `--series <identifier>` - Series identifier or name
- `--asset <uuid>` - Asset UUID (must reference an asset with `state='ready'` and `approved_for_broadcast=true`)
- `--virtual-asset <uuid>` - VirtualAsset UUID
- `--rule <json>` - Rule JSON for filtered selection
- `--random <json>` - Random selection rule JSON

## Optional Options

- `--episode-policy <policy>` - Episode selection policy for series content (sequential, syndication, random, seasonal, least-recently-used)
- `--operator-intent <text>` - Operator-defined metadata describing programming intent
- `--json` - Output in JSON format
- `--test-db` - Use test database context

## Contract Rules

### PA-1: Channel and Plan Resolution

**Rule:** The command MUST resolve the channel and plan by their identifiers before creating the program.

**Behavior:**
- If channel is not found → exit 1, error message: "Error: Channel '<identifier>' not found"
- If plan is not found → exit 1, error message: "Error: Plan '<identifier>' not found"
- If plan does not belong to channel → exit 1, error message: "Error: Plan '<plan>' does not belong to channel '<channel>'"

### PA-2: Content Type Validation

**Rule:** Exactly one content type option MUST be specified.

**Behavior:**
- If no content type specified → exit 1, error: "Must specify one content type: --series, --asset, --virtual-asset, --rule, or --random"
- If multiple content types specified → exit 1, error: "Must specify only one content type"

### PA-3: Start Time Validation

**Rule:** Start time MUST be in valid HH:MM format and within valid range (00:00 to 24:00).

**Behavior:**
- Invalid format (e.g., "25:00", "6:00", "06:60") → exit 1, error: "Invalid start time format: <time>. Expected HH:MM"
- Valid format → proceed

### PA-4: Duration Validation

**Rule:** Duration MUST be a positive integer.

**Behavior:**
- Zero or negative → exit 1, error: "Duration must be positive, got: <duration> minutes"
- Non-integer → exit 1, error: "Duration must be an integer"
- Valid → proceed

### PA-5: Content Reference Validation

**Rule:** Content reference MUST be valid for the specified content type.

**Behavior:**
- For `--asset`: Must reference valid Asset UUID with `state='ready'` and `approved_for_broadcast=true`
  - Invalid UUID → exit 1, error: "Invalid asset UUID: <uuid>"
  - Asset not found → exit 1, error: "Asset '<uuid>' not found"
  - Asset not eligible → exit 1, error: "Asset '<uuid>' is not eligible for scheduling (must be ready and approved)"
- For `--virtual-asset`: Must reference valid VirtualAsset UUID
  - Invalid UUID → exit 1, error: "Invalid VirtualAsset UUID: <uuid>"
  - VirtualAsset not found → exit 1, error: "VirtualAsset '<uuid>' not found"
- For `--series`: Must reference valid Series identifier
  - Series not found → exit 1, error: "Series '<identifier>' not found"
- For `--rule` or `--random`: Must be valid JSON
  - Invalid JSON → exit 1, error: "Invalid JSON for rule/random: <error>"

### PA-6: Overlap Detection

**Rule:** The new program MUST NOT overlap with existing programs in the same plan (per ProgramContract P-5).

**Behavior:**
- If overlap detected → exit 1, error: "Program overlaps with existing program(s) in plan"
- If no overlap → proceed

### PA-7: Grid Alignment (Warning)

**Rule:** Duration SHOULD align with channel's grid_block_minutes (warning, not error).

**Behavior:**
- If duration is not a multiple of grid_block_minutes → warning (non-blocking)
- If start time does not align with grid boundaries → warning (non-blocking)
- Warnings are shown but do not prevent program creation

## Success Behavior

On successful creation:

**Exit Code:** 0

**Output (non-JSON):**
```
Program created:
  ID: <program-id>
  Plan: <plan-name>
  Start: <start-time>
  Duration: <duration> minutes
  Content Type: <content-type>
  Content Reference: <content-ref>
```

**Output (JSON):**
```json
{
  "status": "ok",
  "program": {
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
    "created_at": "<timestamp>"
  }
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

### Example 1: Add Series Program

```bash
retrovue channel plan abc xyz program add --start 06:00 --duration 30 --series "Cheers"
```

**Expected:** Program created with series content type.

### Example 2: Add Asset Program

```bash
retrovue channel plan abc xyz program add --start 20:00 --duration 120 --asset 550e8400-e29b-41d4-a716-446655440000
```

**Expected:** Program created with asset content type.

### Example 3: Add Program with Episode Policy

```bash
retrovue channel plan abc xyz program add --start 19:00 --duration 30 --series "Cheers" --episode-policy seasonal --operator-intent "Play Cheers seasonally"
```

**Expected:** Program created with seasonal episode policy.

### Example 4: Invalid - Missing Content Type

```bash
retrovue channel plan abc xyz program add --start 06:00 --duration 30
```

**Expected:** Exit 1, error: "Must specify one content type: --series, --asset, --virtual-asset, --rule, or --random"

### Example 5: Invalid - Overlapping Programs

```bash
retrovue channel plan abc xyz program add --start 06:00 --duration 60 --series "Show1"
retrovue channel plan abc xyz program add --start 06:30 --duration 30 --series "Show2"
```

**Expected:** Second command exits 1, error: "Program overlaps with existing program(s) in plan"

## Test Coverage Requirements

Tests MUST verify:

1. Successful program creation with each content type
2. Channel and plan resolution (valid and invalid cases)
3. Content type validation (none, multiple)
4. Start time validation (valid, invalid format, out of range)
5. Duration validation (positive, zero, negative, non-integer)
6. Content reference validation for each type
7. Overlap detection (overlapping, touching, non-overlapping)
8. Grid alignment warnings
9. JSON output format
10. Error message clarity

## Related Contracts

- [ProgramContract](ProgramContract.md) - Program domain contract rules
- [SchedulePlanInvariantsContract](SchedulePlanInvariantsContract.md) - Plan-level invariants

