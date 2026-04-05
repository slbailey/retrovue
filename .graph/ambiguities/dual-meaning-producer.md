# Ambiguity: dual-meaning “Producer”

**Domain:** systems (disambiguation)

## Terms conflated

**“Producer”** in RetroVue may mean:

| Meaning | Graph target | Use when |
|---------|--------------|----------|
| **Core runtime feed builder** (BlockPlan / plan segments into AIR) | `service:block-plan-producer` (and related session wiring) | Talking about **feeding** the engine from execution artifacts. |
| **Media decode/source inside AIR** (file producer, programmatic producer, tick producer) | `air-playout-engine` internals (not expanded in this graph) | Talking about **frames**, decode, preview/live slots, FFmpeg. |
| **Historical “adapter producer”** (plugin naming around encoders) | Ingest/adapters domain (out of scope unless graph extended) | Talking about **non-AIR** encoder plugins—**do not** confuse with BlockPlanProducer. |

## Resolution rule

Ask: **Whose process boundary?** Core orchestration feeding gRPC → first row. C++ engine and `IProducer` → second row.

## Relationships

See `relationships/cross-domain.yaml` (`ambiguity:dual-meaning-producer`).
