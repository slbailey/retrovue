# INV-PLAYLIST-SEMANTIC-SPLIT-002 — PlaylistEvents may only split content at semantic boundaries

Status: Invariant
Authority Level: Execution Intent
Derived From: PlayoutExecutionModel — Grid Boundaries vs Semantic Boundaries

## Purpose

Prevents grid-level planning artifacts from leaking into the execution layer. Content is split into multiple PlaylistEvents only when execution intent genuinely changes — ad insertion, promo insertion, content transition, operator override, or explicit metadata boundary. Grid block edges, broadcast day boundaries, and horizon extension boundaries are NOT valid split points.

## Guarantee

A ScheduleItem that produces multiple content-kind PlaylistEvents must have a semantic boundary at each split point. Valid semantic boundaries are:

- **Ad insertion** — An ad break interrupts content.
- **Promo insertion** — A promo interrupts content.
- **Content transition** — One ScheduleItem ends and the next begins.
- **Operator override** — An operator command replaces a segment of content.
- **Explicit metadata boundary** — A point where metadata changes require a new event (e.g., rating change, parental advisory trigger).

Invalid split points (MUST NOT cause splitting):

- Grid block boundaries (fences)
- Broadcast day boundaries
- Horizon extension boundaries

## Preconditions

- PlaylistEvents have been generated from one or more ScheduleItems.
- The ScheduleItem's content requires no interruption (no ad/promo/override/metadata markers).

## Observability

For each ScheduleItem, collect all content-kind PlaylistEvents that reference it. If more than one exists, each split point must correspond to a non-content PlaylistEvent (ad, promo, override) or a documented metadata boundary between the content events. A content-to-content adjacency without an intervening semantic event is a violation.

## Deterministic Testability

Generate PlaylistEvents from a ScheduleItem that spans multiple grid blocks with no ad/promo markers. Assert exactly one content PlaylistEvent is produced. Then generate from a ScheduleItem with known ad break markers and assert the correct number of splits.

## Failure Semantics

**Generation fault.** The PlaylistEvent generator is splitting content at non-semantic boundaries, likely propagating grid block structure into the execution layer.

## Required Tests

- `pkg/core/tests/contracts/playout/test_playlist_semantic_splitting.py::test_grid_boundaries_do_not_split_content`
- `pkg/core/tests/contracts/playout/test_playlist_semantic_splitting.py::test_ad_break_creates_split`
- `pkg/core/tests/contracts/playout/test_playlist_semantic_splitting.py::test_content_transition_creates_split`
