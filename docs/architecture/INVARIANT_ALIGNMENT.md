# Invariant Alignment and Ownership Model

**Status:** Canonical  
**Scope:** RetroVue AIR runtime + cross-domain control boundary  
**Purpose:** Ensure every invariant has a single owner, a single enforcement locus, and a single contract home.

---

## 1. Prime Rule

> **An invariant is only “real” if:**
> 1) it appears in the Canonical Rule Ledger, and  
> 2) it has exactly one owning component, and  
> 3) its contract file lives under the correct layer directory.

If code enforces a rule that is not (1)(2)(3), the code is wrong.

---

## 2. Ownership is a Routing Table

Ownership answers: **“Who must change when this invariant fails?”**

Each invariant must name **one** owner from:

- MasterClock
- TimelineController
- PlayoutEngine
- ProgramOutput (FrameSelection)
- OutputBus
- EncoderPipeline
- MpegTSOutputSink
- FileProducer
- PadProducer
- Core Scheduler (cross-domain)
- Control Plane Protocol (cross-domain)

If multiple components participate, the invariant must be **split** into:
- a single “authority” invariant (owner = authority component)
- one or more “compliance” invariants (owners = participating components)

---

## 3. Layering: Where contracts live

Contracts must be filed by *what they are*, not by who wrote them.

### 3.1 Laws (docs/contracts/laws/)
**Definition:** constitutional, non-negotiable guarantees.  
**Properties:** minimal count, stable, broad.

Examples:
- LAW-AUTHORITY-HIERARCHY
- LAW-CLOCK
- LAW-TIMELINE
- LAW-OUTPUT-LIVENESS
- LAW-SWITCHING
- LAW-AUDIO-FORMAT
- LAW-VIDEO-DECODABILITY
- LAW-OBS-00X

### 3.2 Semantics (docs/contracts/semantics/)
**Definition:** truths about correctness and meaning of time/frames/PTS/CT.

Examples:
- INV-P8-001..012
- INV-P8-SEGMENT-EOF-DISTINCT-001
- INV-P8-CONTENT-DEFICIT-FILL-001
- INV-P10-REALTIME-THROUGHPUT
- INV-PACING-001 / INV-PACING-ENFORCEMENT-002

### 3.3 Coordination (docs/contracts/coordination/)
**Definition:** orchestration rules, readiness, state machines, attachment behavior.

Examples:
- INV-P9-SINK-LIVENESS-00X
- INV-P8-SWITCH-00X
- INV-BOUNDARY-DECLARED-001
- INV-SWITCH-DEADLINE-AUTHORITATIVE-001
- INV-BOUNDARY-LIFECYCLE-001
- INV-TEARDOWN-... / INV-LIVE-SESSION-AUTHORITY-001

### 3.4 Diagnostics (docs/contracts/diagnostics/)
**Definition:** logging/metrics requirements and “must report” rules.  
Must never gate runtime.

Examples:
- INV-P10-PAD-REASON
- INV-P10-FRAME-DROP-POLICY
- INV-P8-WRITE-BARRIER-DIAG

### 3.5 Tasks (docs/contracts/tasks/)
Task specs and phase plans only.  
No canonical rules live here.

---

## 4. The Ledger is an Index, not a home

The Canonical Rule Ledger is the **single source of truth** for:
- which rules exist
- current status (active/superseded/proposed)
- ownership + enforcement phase
- test obligations

But the *actual contract text* must live in its layer file.

---

## 5. “One rule, one home” filing convention

Each layer contains a small number of **compiled** contract files, not one file per invariant.

Recommended compilation scheme:

- docs/contracts/laws/BROADCAST_LAWS.md
- docs/contracts/semantics/PHASE8_SEMANTICS.md
- docs/contracts/coordination/PHASE8_COORDINATION.md
- docs/contracts/coordination/PHASE9_BOOTSTRAP.md
- docs/contracts/coordination/PHASE10_FLOW_CONTROL.md
- docs/contracts/coordination/PHASE12_SESSION_TEARDOWN.md
- docs/contracts/diagnostics/DIAGNOSTIC_INVARIANTS.md

Rule text lives in the compiled file; the ledger references the compiled file + section.

---

## 6. Enforcement locality rule

> If an invariant is owned by component X, enforcement must be implementable inside component X without requiring “polite behavior” from others.

If enforcement requires cooperation, split it into:
- authority invariant (X)
- compliance invariant(s) (others)

---

## 7. Migration rule

During refactor:
- code may temporarily violate the constitution **only if**
  - the violation is documented in MIGRATION_PLAN.md
  - the violation has an owner + removal milestone
  - there is a test or log that will flip from “expected fail” to “pass”

No undocumented temporary exceptions.