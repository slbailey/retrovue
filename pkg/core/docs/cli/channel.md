# Channel Commands

_Related: [Channel Contracts](../contracts/resources/ChannelContract.md) • [Channel Domain](../domain/Channel.md)_

## Overview

Channel commands manage broadcast channels and their configuration.

## Commands

### `retrovue channel list`

List all channels.

**Syntax:**
```bash
retrovue channel list [--json] [--test-db]
```

**Examples:**
```bash
retrovue channel list
retrovue channel list --json
```

### `retrovue channel add`

Create a new broadcast channel.

**Syntax:**
```bash
retrovue channel add --name <name> --grid-size-minutes <size> [options] [--json] [--test-db]
```

**Required Options:**
- `--name <name>` - Channel name (unique)
- `--grid-size-minutes <size>` - Grid size in minutes (15, 30, or 60)

**Optional Options:**
- `--grid-offset-minutes <offset>` - Grid alignment offset (default: 0)
- `--broadcast-day-start <time>` - Programming day anchor in HH:MM format (default: 06:00)
- `--active/--inactive` - Initial active state (default: active)
- `--json` - Output in JSON format
- `--test-db` - Use test database

**Examples:**
```bash
retrovue channel add --name "RetroToons" --grid-size-minutes 30
retrovue channel add --name "MidnightMovies" --grid-size-minutes 60 --broadcast-day-start "05:00"
```

### `retrovue channel show`

Show detailed channel information.

**Syntax:**
```bash
retrovue channel show <channel-id> [--json] [--test-db]
```

**Arguments:**
- `<channel-id>` - Channel UUID or slug

**Examples:**
```bash
retrovue channel show retrotoons
retrovue channel show 550e8400-e29b-41d4-a716-446655440000 --json
```

### `retrovue channel update`

Update channel configuration.

**Syntax:**
```bash
retrovue channel update <channel-id> [options] [--json] [--test-db]
```

**Arguments:**
- `<channel-id>` - Channel UUID or slug

**Options:**
- `--name <name>` - Update channel name
- `--grid-size-minutes <size>` - Update grid size
- `--grid-offset-minutes <offset>` - Update grid offset
- `--broadcast-day-start <time>` - Update programming day anchor
- `--active/--inactive` - Update active state

**Examples:**
```bash
retrovue channel update retrotoons --name "RetroToons HD"
retrovue channel update retrotoons --broadcast-day-start "07:00"
```

### `retrovue channel validate`

Validate channel configuration and dependencies.

**Syntax:**
```bash
retrovue channel validate <channel-id> [--json] [--test-db]
```

**Examples:**
```bash
retrovue channel validate retrotoons
retrovue channel validate retrotoons --json
```

## Plan Commands

### `retrovue channel plan add`

Create a new schedule plan for a channel.

**Syntax:**
```bash
retrovue channel plan add <channel> [--name <name>] [--json] [--test-db]
```

**Required Arguments:**
- `<channel>` - Channel identifier (UUID or slug)

**Optional Options:**
- `--name <name>` - Plan name
- `--json` - Output in JSON format
- `--test-db` - Use test database

**Examples:**
```bash
retrovue channel plan add abc --name "Weekday Plan"
retrovue channel plan add abc --name "Holiday Plan" --json
```

### `retrovue channel plan list`

List all plans for a channel.

**Syntax:**
```bash
retrovue channel plan list <channel> [--json] [--test-db]
```

**Required Arguments:**
- `<channel>` - Channel identifier (UUID or slug)

**Optional Options:**
- `--json` - Output in JSON format
- `--test-db` - Use test database

**Examples:**
```bash
retrovue channel plan list abc
retrovue channel plan list abc --json
```

## Program Commands

### `retrovue channel plan <channel> <plan> program add`

Add a program to a schedule plan.

**Syntax:**
```bash
retrovue channel plan <channel> <plan> program add --start <time> --duration <minutes> [content-options] [--json] [--test-db]
```

**Required Arguments:**
- `<channel>` - Channel identifier (UUID or slug)
- `<plan>` - Plan identifier (UUID or name)

**Required Options:**
- `--start <time>` - Start time in HH:MM format (schedule-time, relative to broadcast day)
- `--duration <minutes>` - Duration in minutes

**Content Type Options (must specify exactly one):**
- `--series <identifier>` - Series identifier or name
- `--asset <uuid>` - Asset UUID
- `--virtual-asset <uuid>` - VirtualAsset UUID
- `--rule <json>` - Rule JSON for filtered selection
- `--random <json>` - Random selection rule JSON

**Optional Options:**
- `--episode-policy <policy>` - Episode selection policy (sequential, syndication, random, seasonal)
- `--operator-intent <text>` - Operator-defined metadata describing programming intent
- `--json` - Output in JSON format
- `--test-db` - Use test database

**Examples:**
```bash
retrovue channel plan abc xyz program add --start 06:00 --duration 30 --series "Cheers"
retrovue channel plan abc xyz program add --start 20:00 --duration 120 --asset 550e8400-e29b-41d4-a716-446655440000
retrovue channel plan abc xyz program add --start 22:00 --duration 120 --virtual-asset 550e8400-e29b-41d4-a716-446655440000
retrovue channel plan abc xyz program add --start 14:00 --duration 90 --rule '{"genre":"family","max_duration":120}'
```

### `retrovue channel plan <channel> <plan> program list`

List all programs in a schedule plan.

**Syntax:**
```bash
retrovue channel plan <channel> <plan> program list [--json] [--test-db]
```

**Required Arguments:**
- `<channel>` - Channel identifier (UUID or slug)
- `<plan>` - Plan identifier (UUID or name)

**Optional Options:**
- `--json` - Output in JSON format
- `--test-db` - Use test database

**Examples:**
```bash
retrovue channel plan abc xyz program list
retrovue channel plan abc xyz program list --json
```

### `retrovue channel plan <channel> <plan> program delete`

Delete a program from a schedule plan.

**Syntax:**
```bash
retrovue channel plan <channel> <plan> program delete <program-id> [--yes] [--json] [--test-db]
```

**Required Arguments:**
- `<channel>` - Channel identifier (UUID or slug)
- `<plan>` - Plan identifier (UUID or name)
- `<program-id>` - Program UUID to delete

**Required Options:**
- `--yes` - Confirm deletion (required for non-interactive use)

**Optional Options:**
- `--json` - Output in JSON format
- `--test-db` - Use test database

**Examples:**
```bash
retrovue channel plan abc xyz program delete 1234 --yes
retrovue channel plan abc xyz program delete 1234 --yes --json
```

## See also

- [Channel Add Contract](../contracts/resources/ChannelAddContract.md) - Create channel behavior
- [Channel Update Contract](../contracts/resources/ChannelUpdateContract.md) - Update channel behavior
- [Program Add Contract](../contracts/resources/ProgramAddContract.md) - Add program behavior
- [Program List Contract](../contracts/resources/ProgramListContract.md) - List programs behavior
- [Program Delete Contract](../contracts/resources/ProgramDeleteContract.md) - Delete program behavior
- [Program Contract](../contracts/resources/ProgramContract.md) - Program domain contract
- [Channel Domain](../domain/Channel.md) - Domain model
- [Program Domain](../domain/Program.md) - Program domain model

