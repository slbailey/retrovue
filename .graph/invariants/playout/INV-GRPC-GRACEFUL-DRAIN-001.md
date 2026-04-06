# INV-GRPC-GRACEFUL-DRAIN-001

**Domain:** playout (Core↔AIR coordination)

## Plain-language rule

`StopBlockPlanSession` drains the current block and emits final evidence (BlockFence, ChannelTerminated, SessionEnded) before termination. Core waits for `SessionEnded` before killing the AIR process.

## Why it exists

Prevents evidence loss and incomplete as-run records on channel teardown. Ensures every playout session has a clean terminal state.

## What it constrains

- **Services:** `playout-session` / `channel-manager` (Core stop logic), `air-playout-engine` (drain execution).
- Stop is idempotent: calling stop on an already-stopped session returns success.
- If `SessionEnded` not received within timeout, Core escalates to SIGTERM then SIGKILL.

## Failure mode if violated

Evidence lost on teardown; as-run records incomplete; orphaned AIR processes; channel stuck in "stopping" state.
