# ProducerBus (Input Bus) Contract

_Related: [Playout Engine Contract](PlayoutEngineContract.md) · [PlayoutInstance & ProgramFormat](PlayoutInstanceAndProgramFormatContract.md) · [OutputBus & OutputSink](OutputBusAndOutputSinkContract.md)_

**Status:** Locked (reflects current code)  
**Scope:** Air (C++) playout engine — input path (producer → buffer)  
**Audience:** Engine implementers, refactor tools (Cursor), future maintainers

---

## 1. Purpose

This contract defines the **input path** in Air: how content producers (e.g. FileProducer) are routed into the playout pipeline. Air has **two producer buses**, **preview** and **live**. Core directs which bus is loaded and which is on-air via gRPC (legacy preload RPC, legacy switch RPC). The active (live) producer feeds the FrameRingBuffer; ProgramOutput consumes the buffer and routes to OutputBus → OutputSink.

OutputBus is documented separately (output path to the sink). This contract documents the **input bus** (ProducerBus) so the full signal path is clear: **ProducerBus (preview + live) → active producer → FrameRingBuffer → ProgramOutput → OutputBus → OutputSink**.

**Control model:** The preview/live bus model is **command-driven**. Core performs THINK (timeline, what plays next, when to transition); Air performs ACT (executes explicit commands). Air **does not** track asset duration, detect producer EOF, or initiate transitions. All content transitions occur **only** when Core issues a command (e.g. legacy switch RPC). Air never switches buses autonomously except when entering **dead-man failsafe** (see §2.4).

---

## 2. Core Definitions (Normative)

### 2.1 ProducerBus (input bus)

**ProducerBus** represents a routed producer input path (e.g. **PREVIEW** or **LIVE**) in a playout session.

- **A bus is not storage.** It holds a reference to an IProducer (e.g. FileProducer) and metadata (loaded, asset_id, file_path). The producer pushes frames into the FrameRingBuffer; the bus does not store frames.
- **A bus may be empty, primed, or active.** Empty = no producer. Primed = producer loaded and decoding (e.g. preview bus after legacy preload RPC). Active = producer is the one currently feeding output (live bus).
- **PlayoutControl** owns two ProducerBuses: **preview bus** and **live bus**. It enforces valid sequencing (e.g. legacy preload RPC loads the preview bus; legacy switch RPC promotes preview to live atomically).

**Code:** `include/retrovue/runtime/ProducerBus.h` — struct ProducerBus (producer, loaded, asset_id, file_path). PlayoutControl holds `ProducerBus previewBus` and `ProducerBus liveBus`.

### 2.2 Preview bus and live bus

| Bus       | Role                                                                 | Driven by Core via gRPC                    |
|-----------|----------------------------------------------------------------------|--------------------------------------------|
| **Preview** | Holds the “next” producer (e.g. FileProducer decoding next segment). | legacy preload RPC (asset_path, start_offset_ms). |
| **Live**    | Holds the producer currently on-air; its output goes to the sink.    | StartChannel (initial); legacy switch RPC (promote preview → live). |

- **legacy preload RPC:** Core sends segment (asset_path, start_offset_ms, hard_stop_time_ms). Air loads that segment on the **preview** bus (shadow decode). The **live** bus is unchanged until legacy switch RPC.
- **legacy switch RPC:** Core commands Air to promote the preview bus to live. Air atomically makes the preview producer the new live producer (and stops/clears the old live producer). PTS continuity is preserved (see Phase 8.3).

The **live** bus’s producer is the one whose output is consumed by ProgramOutput and sent to OutputBus → OutputSink. The **preview** bus is used only to prime the next segment; it does not feed output until legacy switch RPC.

### 2.3 Relation to FrameRingBuffer and ProgramOutput

- The **active (live) producer** pushes decoded frames into the **FrameRingBuffer**.
- **ProgramOutput** consumes the buffer and routes frames to **OutputBus** (when connected).
- OutputBus routes to the attached **OutputSink** (e.g. MpegTSOutputSink). So the full path is:

**ProducerBus (live) → IProducer (e.g. FileProducer) → FrameRingBuffer → ProgramOutput → OutputBus → OutputSink → client.**

### 2.4 Always-valid-output and dead-man failsafe (normative)

The **sink MUST always receive valid output.** When the **live** producer has frames, Air outputs those frames. If the live producer runs out of frames (EOF, underrun, or Core has not yet issued the next control command), Air **immediately** enters **failsafe mode**: output is switched to an internal **BlackFrameProducer** (black video, no audio). This is a **dead-man fallback**, not a scheduling decision—Air is protecting output continuity until Core explicitly reasserts control (e.g. legacy preload RPC + legacy switch RPC). Air remains in failsafe indefinitely until Core issues the next command. No gaps, freezes, or invalid data. The fallback producer and selection logic are defined in [BlackFrameProducerContract](BlackFrameProducerContract.md).

### 2.5 End PTS / hard stop as safety clamp (normative)

An **end PTS** (or equivalent hard-stop boundary, e.g. derived from `hard_stop_time_ms`) may be provided by Core as part of a playout-ready descriptor. Its purpose is to define a **maximum output boundary** for that producer—a **guardrail**, not a trigger.

- The end PTS is **not** a signal to initiate a transition.
- The end PTS is **not** used by Air to decide *when* to switch producers.
- It exists solely to **prevent output beyond an agreed boundary** (bounds clock skew, late commands, decode variance; prevents content bleed across segments, e.g. program frames into an ad block).

**Air behavior at the boundary:** If a producer reaches its end PTS and Core has not yet issued the next control command:

- Air **MUST NOT** emit frames from that producer beyond the end PTS.
- Air **MUST** clamp output for that producer.
- Air **MUST** continue to satisfy the always-valid-output invariant (e.g. black/silence via BlackFrameProducer or equivalent).

This is a **failsafe containment mechanism**, not a scheduling action. The system prefers **bounded silence/black** over **content bleed**. Transitions still occur **only** via explicit Core commands (e.g. legacy switch RPC).

---

## 3. Position in the Architecture

```
Core (gRPC: legacy preload RPC, legacy switch RPC)
         │
         ▼
PlayoutControl (preview bus, live bus)
         │
         ▼
ProducerBus (preview)  ──legacy preload RPC──►  producer loads next segment
ProducerBus (live)    ──legacy switch RPC──►  preview promoted to live; feeds buffer
         │
         ▼
IProducer (e.g. FileProducer) → FrameRingBuffer → ProgramOutput → OutputBus → OutputSink
```

---

## 4. Responsibilities (Normative)

### 4.1 PlayoutControl MUST

- Own exactly two ProducerBuses: **preview** and **live**.
- Enforce valid sequencing: legacy preload RPC targets preview bus; legacy switch RPC promotes preview to live and clears old live.
- Not allow output to be driven by an undefined or empty live bus without a defined fallback (see [BlackFrameProducerContract](BlackFrameProducerContract.md)).

### 4.2 ProducerBus (struct) MUST

- Hold at most one IProducer per bus (or be empty).
- Expose reset() to clear the bus to empty state.
- Track loaded state and asset identity (asset_id, file_path) for diagnostics and control.

### 4.3 Air MUST NOT

- Expose more than two producer buses (preview, live) in the current design.
- Let the live bus feed output without a valid producer unless a fallback (BlackFrameProducer) is active—see [BlackFrameProducerContract](BlackFrameProducerContract.md).

---

## 5. Invariants (Must Always Hold)

1. There are exactly **two** ProducerBuses per PlayoutInstance: **preview** and **live**.
2. The **live** bus is the one whose producer (if any) feeds the FrameRingBuffer and thus the output path.
3. The **preview** bus is used only for loading the next segment; it does not feed output until promoted to live via legacy switch RPC.
4. **Core directs all transitions.** Air does not detect producer endings, track duration, or initiate transitions. Air switches buses **only** in response to explicit Core commands (e.g. legacy switch RPC) or when entering dead-man failsafe (live producer underrun → BlackFrameProducer).
5. The **sink always receives valid output**: when the live producer runs out of frames and Core has not yet commanded the next action, Air enters dead-man failsafe and switches to BlackFrameProducer (see [BlackFrameProducerContract](BlackFrameProducerContract.md)); no gaps, freezes, or invalid data.
6. **End PTS / hard stop is a guardrail, not a trigger.** Air MUST NOT emit frames beyond the producer's end boundary; at the boundary Air clamps and satisfies always-valid-output (black/silence). Transitions occur only via explicit Core commands.

---

## 6. See Also

- [PlayoutInstanceAndProgramFormatContract](PlayoutInstanceAndProgramFormatContract.md) — PlayoutInstance owns ProducerBus(es).
- [OutputBusAndOutputSinkContract](OutputBusAndOutputSinkContract.md) — Output path (bus + sink).
- [BlackFrameProducerContract](BlackFrameProducerContract.md) — BlackFrameProducer fallback when live producer runs out of frames.
- [LegacyPreviewSwitchModel (Retired model)](../coordination/LegacyPreviewSwitchModel.md) — Core-driven bus switching.
