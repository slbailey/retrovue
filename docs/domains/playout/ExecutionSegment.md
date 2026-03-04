# Entity: ExecutionSegment

**Classification:** Entity Specification (Stub)
**Layer:** Core -> AIR boundary
**Upstream:** PlaylistEvent
**Downstream:** AIR

---

## Purpose

An **ExecutionSegment** is a concrete, frame-accurate playback instruction derived from a PlaylistEvent. It is the final Core-produced artifact before handoff to AIR. ExecutionSegments translate execution intent (PlaylistEvent) into precise asset references, seek positions, and durations that AIR can render without interpretation.

---

## Relationship to PlaylistEvent

Each PlaylistEvent produces one or more ExecutionSegments. The transformation handles:

- Resolving asset offsets to frame-accurate seek positions
- Splitting PlaylistEvent durations into segment-level units suitable for AIR's block execution model
- Attaching segment-level metadata (codec hints, decoder priming requirements, transport descriptors)

ExecutionSegments MUST NOT alter execution intent. They refine presentation within their authority -- frame accuracy, seek precision, segment boundaries -- but the what and when of playout is decided by PlaylistEvent.

---

## Role in AIR Playback

AIR consumes ExecutionSegments exclusively. AIR never sees ScheduleItems or PlaylistEvents.

ExecutionSegments carry everything AIR needs:
- Asset URI and seek position
- Segment duration (frame-accurate)
- Codec and container hints
- Continuity metadata (PTS offsets, segment sequencing)

AIR renders ExecutionSegments in order, enforcing real-time pacing, managing decoder lifecycle, and producing transport stream output.

---

## Ownership

Frame-accurate segmentation belongs here. Responsibilities include:

- Seek position computation from PlaylistEvent offsets
- Frame boundary alignment (snapping to nearest keyframe or exact frame as required)
- Segment-level metadata attachment
- Producing the instruction format AIR expects

ExecutionSegment does NOT decide:
- When ad breaks occur (PlaylistEvent)
- What content airs (ScheduleItem)
- How frames are decoded or paced (AIR)

---

## Schema

Not yet defined. Schema will be specified when ExecutionSegment implementation begins.

---

**Related:** [PlayoutExecutionModel](PlayoutExecutionModel.md) | [PlaylistEvent](PlaylistEvent.md) | [ScheduleItem](../ScheduleItem.md)
