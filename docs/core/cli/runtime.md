# Runtime Commands

_Related: [Runtime Components](../runtime/ChannelManager.md) • [MasterClock Contract](../contracts/resources/MasterClockContract.md)_

## Overview

Runtime commands provide diagnostics and validation for system components during broadcast operation.

## Commands

### `retrovue runtime masterclock`

Validate and diagnose master clock state.

**Syntax:**
```bash
retrovue runtime masterclock [--json]
```

**Examples:**
```bash
retrovue runtime masterclock
retrovue runtime masterclock --json
```

### `retrovue runtime status`

Show runtime system status.

**Syntax:**
```bash
retrovue runtime status [--json]
```

## See also

- [MasterClock Contract](../contracts/resources/MasterClockContract.md) - Master clock specifications
- [ChannelManager](../runtime/ChannelManager.md) - Runtime component documentation

