# BlockPlanProducer

**Domain:** playout  
**Slug:** `block-plan-producer`

## Responsibility

Build and advance **BlockPlan** feeds from **playlog / scheduled execution timing**—Core-side **execution feeder**, not editorial scheduler.

## Owns vs reads

- **Owns:** algorithmic translation from **execution event context** into contiguous BlockPlan messages for AIR.
- **Reads:** timing and material resolution **already present** in the execution path (from **playlog** / execution window), not EPG.

## Upstream inputs

**`playlog`** (and related execution-window state), `playout-session` coordination, wall clock.

## Downstream outputs

Block plan RPC feed to `air-playout-engine`.

## Must NOT do

- Perform Asset Library lookups to **fix** missing planning data at runtime (ChannelManager planning prohibition applies to the execution layer as a whole).
- Derive segment choice from EPG.
- Treat **`playlist`** as the root input when **`playlog`** is the authoritative stream.
