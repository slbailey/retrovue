# SchedulePlan Build Contract

_Related: [SchedulePlan Add](SchedulePlanAddContract.md) • [Domain: SchedulePlan](../../domain/SchedulePlan.md) • [Domain: Channel](../../domain/Channel.md)_

## Purpose

This contract defines the behavior of the `retrovue channel plan <channel> build` command, which creates a new SchedulePlan and enters an interactive REPL (Read-Eval-Print Loop) for building and editing the plan. This command is intended for interactive CLI use, while `plan add` provides the non-interactive API surface for web UI integration. The web UI will call the same underlying Plan Add function used by the CLI; the interactive plan build command exists only for developer and QA workflows, not production usage.

**Coverage Guarantee:** Plans created by this command are automatically initialized with a default test filler zone (SyntheticAsset, 00:00–24:00) to satisfy INV_PLAN_MUST_HAVE_FULL_COVERAGE. Plans must contain one or more Zones whose combined coverage spans 00:00–24:00 with no gaps. This ensures the plan immediately has full 24-hour coverage and can be used for schedule generation. The default zone can be replaced or modified during the REPL session.

## Command Syntax

```bash
retrovue channel plan <channel> build \
  --name <string> \
  [--description <string>] \
  [--cron <cron-expression>] \
  [--start-date <YYYY-MM-DD>] \
  [--end-date <YYYY-MM-DD>] \
  [--priority <integer>] \
  [--active | --inactive] \
  [--test-db]
```

## Required Arguments

- `<channel>` - Channel identifier (UUID or slug)

## Required Options

- `--name <string>` - Plan name (must be unique within the channel)

## Optional Options

- `--description <string>` - Human-readable description of the plan's programming intent
- `--cron <cron-expression>` - Cron-style expression for recurring patterns. **Note:** Only date/day-of-week fields are used (e.g., `* * * * MON-FRI`). Hour and minute fields are parsed but ignored. Cron matching is evaluated against MasterClock (system local time).
- `--start-date <YYYY-MM-DD>` - Start date for plan validity (inclusive, can be year-agnostic)
- `--end-date <YYYY-MM-DD>` - End date for plan validity (inclusive, can be year-agnostic)
- `--priority <integer>` - Priority for layering (default: 0). Higher numbers = higher priority.
- `--active` / `--inactive` - Plan operational status (default: `--active`)
- `--test-db` - Use test database context

**Note:** This command does NOT support `--json` flag as it enters an interactive REPL mode.

## Behavior Contract Rules (B-#)

### B-1: Plan Creation Before REPL

**Rule:** The command MUST create the SchedulePlan before entering REPL mode, using the same validation rules as `plan add`.

**Behavior:**

- Plan is created with all provided parameters
- Same validation rules apply as `plan add` (channel resolution, name uniqueness, date validation, cron validation, priority validation)
- **Default test filler zone initialization**: When no zones are supplied, the system automatically initializes the plan with a default test filler zone (SyntheticAsset, 00:00–24:00) to satisfy INV_PLAN_MUST_HAVE_FULL_COVERAGE. Plans must contain one or more Zones whose combined coverage spans 00:00–24:00 with no gaps. This ensures the plan immediately has full 24-hour coverage and can be used for schedule generation. The default zone can be replaced or modified during the REPL session.
- If plan creation fails, command exits with error (does not enter REPL)
- Plan is created in a transaction that is NOT committed until `save` is called in REPL

### B-2: REPL Entry

**Rule:** Upon successful plan creation, the command MUST enter interactive REPL mode.

**Behavior:**

- Shell prompt changes to: `(plan:<PlanName>)>`
- Command waits for user input
- REPL accepts commands until `save`, `discard`, or `quit` is called
- All changes made in REPL are in-memory until `save` is called

### B-3: REPL Commands

**Rule:** The REPL MUST support the following commands as defined in [SchedulePlan Domain Documentation](../../domain/SchedulePlan.md):

**Available Commands:**

- `zone add <name> --from HH:MM --to HH:MM [--days MON..SUN]` - Creates a new Zone
- `zone asset add <zone> <schedulable-asset-id>` - Adds a SchedulableAsset (Program, Asset, VirtualAsset, SyntheticAsset) to a Zone
- `zone asset remove <zone> <schedulable-asset-id>` - Removes a SchedulableAsset from a Zone
- `program create <name> --play-mode random|sequential|manual [--asset-chain <id1>,<id2>,...]` - Creates a Program with asset_chain and play_mode
- `validate` - Performs validation checks on the current plan
- `preview day YYYY-MM-DD` - Generates a preview of how the plan resolves for a date
- `save` - Saves all changes and exits REPL
- `discard` - Discards all changes and exits REPL
- `quit` - Exits REPL (prompts for confirmation if unsaved changes exist)
- `help` - Shows available REPL commands

**Behavior:**

- Invalid commands show error message and continue REPL
- Command validation errors are displayed but do not exit REPL
- Each command runs in a transaction; failures roll back that command only
- `save` commits all changes made during the session
- `discard` rolls back all changes made during the session

### B-4: Session State

**Rule:** The REPL session maintains state for the plan being edited.

**Behavior:**

- All Zones and SchedulableAssets created during the session are associated with the plan
- Changes are visible immediately within the REPL session
- Changes are NOT persisted until `save` is called
- If `discard` is called, all changes are lost

### B-5: Validation Delegation

**Rule:** All REPL commands MUST delegate validation to the domain layer, using the same validators as CLI operations.

**Behavior:**

- Validation errors propagate as `ValidationError` with `code`, `message`, and `details`
- Error messages are displayed to the user without translation
- Same validation rules apply as non-interactive CLI commands
- Validation failures do not exit REPL; user can correct and retry

### B-6: Transaction Boundaries

**Rule:** Each REPL command runs in its own transaction; `save` commits all changes, `discard` rolls back all changes.

**Behavior:**

- Each command (`zone add`, `zone asset add`, etc.) runs in a single transaction
- If a command fails, only that command's transaction rolls back
- `save` commits all changes made during the entire session
- `discard` rolls back all changes made during the entire session
- Database state before and after a failed operation must be identical

### B-7: Exit Behavior

**Rule:** The REPL MUST exit cleanly on `save`, `discard`, or `quit`.

**Behavior:**

- `save`: Commits all changes, displays success message, exits with code 0
- `discard`: Rolls back all changes, displays message, exits with code 0
- `quit`: If unsaved changes exist, prompts for confirmation; exits with code 0
- Ctrl+C: Prompts for confirmation if unsaved changes exist; exits with code 1 if aborted, 0 if confirmed

## Data Contract Rules (D-#)

### D-1: Plan Creation Transaction

**Rule:** Plan creation and REPL session operate within a single transaction that is committed only on `save`.

**Behavior:**

- Plan is created in a transaction that is NOT auto-committed
- All REPL commands operate within the same transaction context
- Transaction is committed only when `save` is called
- Transaction is rolled back if `discard` is called or session is aborted

### D-2: Atomic Save

**Rule:** The `save` command MUST commit all changes atomically.

**Behavior:**

- All Zones and SchedulableAssets created during the session are persisted together
- If save fails, entire transaction rolls back; no partial state persists
- Plan and all associated entities are persisted in a single transaction

### D-3: Discard Behavior

**Rule:** The `discard` command MUST roll back all changes made during the session.

**Behavior:**

- Plan creation is rolled back
- All Zones and SchedulableAssets created during the session are discarded
- Database state returns to pre-session state
- No partial state persists after discard

## REPL Command Details

### Zone Commands

**`zone add <name> --from HH:MM --to HH:MM [--days MON..SUN]`**

- Creates a new Zone with the specified name and time window
- Optional `--days` parameter restricts Zone to specific days (e.g., `MON..FRI`, `SAT..SUN`)
- Times snap to Channel grid boundaries
- Validates zone overlap with existing zones in the plan
- On success: displays confirmation message
- On failure: displays validation error, REPL continues

**`zone list`**

- Lists all zones in the current plan
- Shows zone name, time window, and day filters

**`zone show <name>`**

- Shows details for a specific zone

### Program Commands

**`program create <name> --type series|movie|block [--rotation random|sequential|lru] [--slot-units N]`**

- Creates a new Program catalog entry
- `--type` specifies Program type (series, movie, or block)
- `--rotation` specifies episode selection policy for series
- `--slot-units` overrides default block count for longform content
- Validates Program name uniqueness
- On success: displays confirmation message

**`program list`**

- Lists all Programs in the catalog

### Validation Commands

**`validate`**

- Performs validation checks on the current plan
- Checks grid alignment, zone overlaps, and policy compliance
- Displays any issues or conflicts
- Does not prevent saving (warnings only)

### Preview Commands

**`preview day YYYY-MM-DD`**

- Generates a preview of how the plan resolves for the specified date
- Shows the first 12 hours rolled from the current Plan
- Compiles to a ScheduleDay draft (not persisted)
- Demonstrates how Zones and SchedulableAssets expand into concrete schedule entries

### Session Commands

**`save`**

- Saves the current plan and all changes
- Persists all Zones and SchedulableAssets to the database
- Commits the transaction
- Displays success message
- Exits REPL with code 0

**`discard`**

- Discards all changes made in Planning Mode
- Rolls back the transaction
- No changes are persisted to the database
- Displays confirmation message
- Exits REPL with code 0

**`quit`**

- Exits Planning Mode without saving
- If unsaved changes exist, prompts: "You have unsaved changes. Are you sure you want to quit? [y/N]: "
- If confirmed or no changes: exits with code 0
- If aborted: exits with code 1

**`help`**

- Displays list of available REPL commands with brief descriptions

## Output Format

### REPL Prompt

```
(plan:<PlanName>)>
```

### Command Success Messages

Commands display brief confirmation messages on success:

```
Zone 'Morning' added: 06:00-12:00
SchedulableAsset added to zone 'Morning': ProgramA
Program 'MySeries' created (type: series, rotation: sequential)
Plan saved successfully.
```

### Error Messages

Validation errors are displayed inline:

```
Error: Zone 'Evening' overlaps with existing zone 'Afternoon'
Error: Program 'NonExistent' not found
```

### Help Output

```
Available commands:
  zone add <name> --from HH:MM --to HH:MM [--days MON..SUN]
  zone list
  zone show <name>
  zone asset add <zone> <schedulable-asset-id>
  zone asset remove <zone> <schedulable-asset-id>
  program create <name> --play-mode random|sequential|manual [--asset-chain <id1>,<id2>,...]
  program list
  validate
  preview day YYYY-MM-DD
  save
  discard
  quit
  help
```

## Exit Codes

- `0`: REPL exited successfully (via `save`, `discard`, or `quit`)
- `1`: Plan creation failed (before entering REPL)
- `1`: REPL aborted (Ctrl+C without confirmation, or quit without confirmation when unsaved changes exist)
- `2`: CLI usage error (missing required arguments)

## Error Conditions

- Channel not found: exit 1, "Error: Channel '<identifier>' not found" (before REPL)
- Duplicate name: exit 1, "Error: Plan name '<name>' already exists in channel '<channel>'" (before REPL)
- Invalid date format: exit 1, "Error: Invalid date format. Use YYYY-MM-DD: <error>" (before REPL)
- Start date after end date: exit 1, "Error: start_date must be <= end_date" (before REPL)
- Invalid cron: exit 1, "Error: Invalid cron expression: <expression>" (before REPL)
- Negative priority: exit 1, "Error: Priority must be non-negative" (before REPL)

## Relationship to `plan add`

- `plan add`: Non-interactive command for API/web UI use; creates plan and exits immediately
- `plan build`: Interactive command for CLI use; creates plan and enters REPL for iterative editing
- Both commands use the same validation rules and create plans with identical structure
- `plan build` is a convenience wrapper that combines `plan add` + REPL session

## Tests

### Behavioral Contract Tests (`test_plan_build_contract.py`)

- `test_plan_build_help_flag_exits_zero` - Help flag behavior
- `test_plan_build_missing_name_exits_one` - Required name validation
- `test_plan_build_channel_not_found_exits_one` - Channel resolution
- `test_plan_build_duplicate_name_exits_one` - Name uniqueness
- `test_plan_build_enters_repl` - REPL entry after plan creation
- `test_plan_build_save_commits_changes` - Save command commits
- `test_plan_build_discard_rolls_back_changes` - Discard command rolls back
- `test_plan_build_quit_without_changes_exits_zero` - Quit without changes
- `test_plan_build_quit_with_unsaved_changes_prompts` - Quit with unsaved changes prompts
- `test_plan_build_quit_with_unsaved_changes_cancelled` - Cancelled quit continues REPL
- `test_plan_build_help_command` - Help command displays commands
- `test_plan_build_invalid_command` - Invalid commands show error and continue

### Data Contract Tests (`test_plan_build_data_contract.py`)

- `test_plan_build_creates_plan_before_repl` - Plan creation before REPL (D-1)
- `test_plan_build_save_persists_all_entities` - Save commits atomically (D-2)
- `test_plan_build_discard_rolls_back_all_changes` - Discard rolls back (D-3)
- `test_plan_build_transaction_not_committed_until_save` - Transaction not committed until save (D-1)
- `test_plan_build_save_failure_rolls_back` - Save failure rolls back (D-2)
- `test_plan_build_plan_creation_uses_same_validation_as_add` - Validation consistency (D-1)

## See Also

- [SchedulePlan Add Contract](SchedulePlanAddContract.md) - Non-interactive plan creation
- [SchedulePlan Domain Documentation](../../domain/SchedulePlan.md) - Planning Mode REPL specification
- [Zones + SchedulableAssets contracts](../ZonesPatterns.md) - Scheduling behavior guarantees
- [Zone domain](../../domain/Zone.md) - Zone concept and invariants
- [Program Contract](ProgramContract.md) - Program catalog operations

