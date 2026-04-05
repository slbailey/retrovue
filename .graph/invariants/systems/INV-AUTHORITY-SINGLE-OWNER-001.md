# INV-AUTHORITY-SINGLE-OWNER-001

**Domain:** systems

## Plain-language rule

For each **designated concern**, exactly **one** Core component **writes** that kind of state; others may **read**. Documented slices include: **orchestration clock** (`master-clock`), **HLS segment window** (`segment-ring`), **channel lifecycle** (`program-director`), **HLS diagnostics** (per-channel state held by PD as contracted).

## Why it exists

Stops “two bosses” bugs: silent divergence, fixes that break three other places, and logs that cannot identify a single decision maker.

## What it constrains

- **Services:** all Core runtime services that might **tempt** duplicate clocks, rings, lifecycle, or diagnostics ownership.

## Failure mode if violated

Race-prone fixes, inconsistent manifests vs segment store, duplicated teardown logic, and **untraceable** runtime state.

## Note

Full authoritative prose lives in RetroVue root `CLAUDE.md` (authority rule); this file is the graph’s actionable summary. **AIR** has its own internal authorities—do not merge into Core slices.
