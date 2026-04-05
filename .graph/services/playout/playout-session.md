# PlayoutSession

**Domain:** playout  
**Slug:** `playout-session`

## Responsibility

Coordinate **session-scoped** playout orchestration glue for BlockPlan mode: credits, feed results, interaction between producer and `channel-manager`/`block-plan-producer` as contracted.

## Owns vs reads

- **Owns:** session-level orchestration state **in Core** for the active playout path (not AIR internal state).
- **Reads:** feed signals, timing, and policies from runtime configuration.

## Upstream inputs

Channel activation, block feed callbacks, scheduler of runtime loop.

## Downstream outputs

Commands/data toward AIR via `channel-manager` path.

## Must NOT do

- Replace `channel-manager` as owner of AIR process lifecycle.
- Replace scheduling horizon publication (scheduling domain).
