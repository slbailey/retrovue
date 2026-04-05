# ExecutionEntry

**Domain:** scheduling  
**Slug:** `execution-entry`

## What it represents

The **execution plan** slice: sole **runtime scheduling authority**—ordered records (within the locked horizon) for what should execute when—**not** EPG and not ad hoc runtime invention.

## Lifecycle phase

**Derived** from TransmissionLog / ScheduleDay chain, then **locked** in the execution window per immutability and lookahead rules.

## Owning domain

scheduling (execution artifact); playout **consumes** it only via **playlog / event materialization**, not by re-planning.

## What depends on it

**Playlog / automation event** construction (horizon pipeline); downstream **`playlist`-shaped** views if used.

## What produces it

Scheduling pipeline (horizon manager / derivation stack)—not ChannelManager.

## What must NOT be assumed

- That EPG can substitute for it at runtime.
- That ChannelManager may extend or repair it during consumption (forbidden by execution-boundary invariants).
- That a **playlist** file or type can replace this as authority—it may only **reflect** it.
