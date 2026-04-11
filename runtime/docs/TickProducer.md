# What is a TickProducer?

## The short version

A TickProducer is the thing that decodes video and audio frames from a media
file during playout. It does not decide *when* to decode -- it just decodes
*on demand*, one frame at a time, whenever the engine asks for one.

The engine says "give me the next frame." TickProducer either hands back a
decoded frame or says "I've got nothing" (and the engine fills in a black
frame instead). That's the entire relationship.

## Why "tick"?

AIR's PipelineManager runs a loop that fires once per frame -- roughly 30
times a second at 30fps. Each iteration of that loop is a **tick**. The
engine owns the clock. TickProducer does not have its own timer, thread, or
pacing logic. It is completely passive: called once per tick, returns one
frame per call.

This is different from the other producers in AIR (FileProducer,
ProgrammaticProducer, BlackFrameProducer) which run their own internal
threads and push frames into a buffer. TickProducer is **pull-based** -- the
engine pulls frames out of it at exactly the rate it needs them.

## How it fits into a playout session

```
Core sends a block plan
         |
         v
  PipelineManager (the engine)
         |
    each tick:
         |--- "give me a frame" ---> TickProducer
         |<-- frame or nothing -----/
         |
         v
    Encoder --> MPEG-TS bytes --> Viewer
```

1. Core tells AIR what to play (a "block" -- a chunk of scheduled content).
2. PipelineManager hands the block to a TickProducer via `AssignBlock()`.
   This opens the media file, seeks to the right position, etc.
3. Every tick, PipelineManager calls `TryGetFrame()`. TickProducer decodes
   one frame and hands it back.
4. When the block's allocated time is up (the "fence"), PipelineManager
   moves on to the next block.

## The two-state machine

TickProducer has exactly two states:

```
EMPTY  ----AssignBlock()---->  READY
READY  ----Reset()---------->  EMPTY
```

- **EMPTY**: No block assigned. `TryGetFrame()` returns nothing.
- **READY**: Block assigned. Decoding may or may not work (the file might be
  missing), but the state is READY regardless. If decoding fails, the engine
  gets "nothing" and fills in a black pad frame.

There is no "exhausted" or "done" state. The engine decides when a block is
finished by counting ticks against `FramesPerBlock()`. TickProducer itself
never says "I'm done."

## Why does it implement IProducer?

AIR has a system-wide interface called `IProducer` that all producers
implement (FileProducer, BlackFrameProducer, ProgrammaticProducer, etc.).
It provides a common identity: start/stop lifecycle, cooperative shutdown
via `RequestStop()`, and optional as-run stats.

TickProducer implements `IProducer` so that PipelineManager can hold its
producers as `IProducer` pointers -- the same type the rest of AIR uses.
This means PipelineManager's producers are visible to the rest of the system
in a uniform way, even though internally they work differently (tick-driven
instead of thread-driven).

The `IProducer` methods on TickProducer are simple bookkeeping:

| Method             | What it does                              |
|--------------------|-------------------------------------------|
| `start()`          | Sets a "running" flag. Returns true.      |
| `stop()`           | Resets the decoder, clears "running".     |
| `isRunning()`      | Returns the "running" flag.               |
| `RequestStop()`    | Sets a "please stop" flag.                |
| `IsStopped()`      | Returns true if not running.              |
| `GetAsRunFrameStats()` | Returns nothing (not applicable here).|

These exist for interface conformance. The real work happens through the
tick methods (`AssignBlock`, `TryGetFrame`, `Reset`).

## Why does ITickProducer exist as a separate interface?

`ITickProducer` is the interface that defines the tick-driven methods.
It exists so that PipelineManager can store producers as generic `IProducer`
pointers but still call the blockplan-specific tick methods when it needs to.
PipelineManager does a `dynamic_cast<ITickProducer*>` to access them.

Think of it as two badges on the same person:
- **IProducer badge**: "I'm a producer, the system can manage my lifecycle."
- **ITickProducer badge**: "I speak the tick protocol that PipelineManager uses."

TickProducer wears both badges. PipelineManager checks for the second one
when it needs to do tick-specific work.

## Summary

- TickProducer decodes media frames one at a time, on demand.
- It has no clock, no thread, no timer. The engine drives it.
- It implements IProducer (system identity) + ITickProducer (tick methods).
- Two states: EMPTY and READY. The engine decides when blocks start and end.
- If decoding fails for any reason, the engine pads with black frames. The
  show goes on.
