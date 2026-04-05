# BlockPlan

**Domain:** playout  
**Slug:** `block-plan`

## What it represents

The **Core→AIR execution unit** for BlockPlan mode: contiguous scheduled blocks with fence semantics, fed just-in-time per gRPC contract (queue depth, continuity rules).

## Lifecycle phase

**Runtime** planning artifact assembled in Core for an active session; **not** persisted editorial truth.

## Owning domain

playout (orchestration); **AIR** executes what it is fed.

## What depends on it

AIR BlockPlan session RPCs, lookahead feeding, seam readiness.

## What produces it

`block-plan-producer` / `playout-session` logic from execution artifacts—not from EPG.

## What must NOT be assumed

- That BlockPlan replaces SchedulePlan (different layer: **execution feed** vs **editorial**).
- That AIR invents block boundaries from EPG or schedules.
