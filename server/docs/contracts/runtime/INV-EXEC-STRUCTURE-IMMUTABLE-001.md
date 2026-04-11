# INV-EXEC-STRUCTURE-IMMUTABLE-001: ScheduledBlock Time Bounds Immutable at Execution

**Component:** Core / ChannelManager
**Enforcement:** Runtime (`channel_manager.py`)
**Created:** 2026-02-12

---

## Definition

> Execution SHALL treat `ScheduledBlock.start_utc_ms` and `end_utc_ms` as authoritative and SHALL NOT modify them.

---

## Scope

- **Applies to:** Any code path in ChannelManager (or execution layer) that receives, holds, or forwards a `ScheduledBlock` (or equivalent playout-plan entry with `start_utc_ms` / `end_utc_ms`).
- **Authoritative source:** Scheduling/planning (e.g. ScheduleManager, burn_in, BlockPlan) owns and sets these values. Execution consumes them for timing (preload deadlines, boundary declaration, feed ordering) but MUST NOT overwrite, adjust, or recompute `start_utc_ms` or `end_utc_ms` on the block.

---

## Rationale

- Editorial and schedule truth live in Core; block time bounds are part of that truth.
- Execution must not "fix" or realign block times (e.g. to grid or to "now"); such logic belongs in planning.
- Preserving immutability at execution keeps a single source of truth and avoids drift between what was planned and what was executed.

---

## Enforcement

- ChannelManager MUST NOT assign to `block.start_utc_ms` or `block.end_utc_ms` (or to equivalent dict keys) for any block received from the plan.
- Derived values (e.g. `duration_ms`, `ready_by_utc_ms`, `_next_block_start_ms`) MAY be computed from these fields but MUST NOT be written back onto the block.
- When building structures to send downstream (e.g. to AIR), execution MUST pass through the same `start_utc_ms` / `end_utc_ms` values it received.
