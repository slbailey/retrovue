# Producer Commands

_Related: [Producer Domain](../domain/PlayoutPipeline.md)_

## Overview

Producer commands manage producer instances for playout generation.

## Commands

### `retrovue producer list`

List all producers.

**Syntax:**
```bash
retrovue producer list [--json]
```

### `retrovue producer add`

Create a producer instance.

**Syntax:**
```bash
retrovue producer add --type <type> --name <name> [options] [--json]
```

### `retrovue producer remove`

Remove a producer.

**Syntax:**
```bash
retrovue producer remove <producer-id> [--force] [--confirm] [--json]
```

## See also

- [Playout Pipeline](../domain/PlayoutPipeline.md) - Producer architecture

