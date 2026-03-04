# Domain: ScheduleRevision

## Purpose

A **ScheduleRevision** is an immutable snapshot of the editorial schedule for a single channel and broadcast_day.

Canonical pipeline:

```
SchedulePlan → ScheduleRevision → ScheduleItem → PlaylistEvent → ExecutionSegment → BlockPlan → AIR → AsRun
```

ScheduleRevision groups **ScheduleItems** into a versioned unit that can be activated atomically. Once active, the revision's ScheduleItems are frozen — downstream derivation (PlaylistEvent generation) always reads from the active revision, and no mutation can silently corrupt the derivation chain.

**What ScheduleRevision provides:**
- Immutable editorial snapshots that downstream artifacts can trust
- Safe schedule updates without race conditions with playout
- Audit history of schedule changes (superseded revisions are retained)
- Atomic activation — the schedule switches from one complete revision to another, never partially

> **Note:**
> ScheduleRevision does *not* define playout behavior.
> It governs editorial truth ownership at the Tier 1 (editorial) boundary.

---

## Authority

| Property | Value |
|----------|-------|
| **Layer** | Tier 1 (editorial) |
| **Owner** | Scheduler (DSL compiler / editorial scheduling) |
| **Scope** | One channel, one broadcast_day |
| **Mutability** | Immutable once activated |

ScheduleRevision is the authoritative container for ScheduleItems. All ScheduleItems belong to exactly one ScheduleRevision. A channel may have multiple revisions over time, but exactly one revision may be active at any moment. The active ScheduleRevision defines the editorial truth from which all downstream artifacts are derived.

```
SchedulePlan
   ↓ compile
ScheduleRevision
   ↓ owns
ScheduleItem
   ↓ derives
PlaylistEvent
```

---

## Lifecycle

A ScheduleRevision transitions through three states:

```
draft → active → superseded
```

| State | Meaning | ScheduleItem mutability | Visible to Tier 2 |
|-------|---------|------------------------|--------------------|
| **draft** | Under construction. ScheduleItems being created by the compiler. | Mutable | No |
| **active** | Frozen. This is the editorial truth for the channel + broadcast_day. Exactly one active ScheduleRevision per channel at a time. Tier 2 derives from it. | Immutable | Yes |
| **superseded** | Replaced by a newer active revision. Retained for audit only. | Immutable | No |

### Activation rules

- Activating a draft revision atomically transitions it to `active`.
- If another revision was previously active for the same (channel_id, broadcast_day), it transitions to `superseded` in the same operation.
- A channel has **exactly one** active ScheduleRevision per broadcast_day at any time.
- Activation is all-or-nothing. There is no partial activation.

### Supersession rules

- A superseded revision is never reactivated. To restore a previous schedule, create a new revision with equivalent content.
- Superseded revisions and their ScheduleItems are retained for audit and traceability.

---

## Relationships

```
Channel
   └── broadcast_day
          └── ScheduleRevision (exactly one active)
                 └── ScheduleItem (1-many)
                        ↓
                     PlaylistEvent (Tier 2 derivation)
```

- **ScheduleRevision** belongs to a `(channel_id, broadcast_day)` scope.
- **ScheduleRevision** contains one or more **ScheduleItems**. Each ScheduleItem belongs to exactly one ScheduleRevision.
- **PlaylistEvent** generation derives from ScheduleItems in the active ScheduleRevision only.

---

## Invariants Summary

| Invariant | Description |
|-----------|-------------|
| `INV-SCHEDULEREVISION-IMMUTABLE-001` | Once activated, a ScheduleRevision's ScheduleItems must not be mutated. |
| *(no ID yet)* | A channel has exactly one active ScheduleRevision per broadcast_day at any time. |
| *(no ID yet)* | A ScheduleItem belongs to exactly one ScheduleRevision. |

---

## Non-Goals

- **Database schema.** Persistence design is deferred. This document defines the domain model only.
- **Distributed coordination.** Multi-node activation semantics are a future concern.
- **Partial revision activation.** A revision is activated atomically — all-or-nothing. There is no mechanism to activate a subset of its ScheduleItems.
- **Diff/merge between revisions.** Revisions are opaque snapshots. Comparing two revisions is an operator tooling concern, not a domain model concern.
