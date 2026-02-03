# Retired Invariants (Historical Reference)

**Status:** Historical
**Purpose:** Document superseded rules for reference and audit trail
**Authority:** None - these rules are no longer enforced

---

## Superseded Rules

These rules from RULE_HARVEST and earlier phases are explicitly superseded and should not be enforced.

| Original Rule | Superseded By | Reason | Date |
|---------------|---------------|--------|------|
| RULE_HARVEST #3 (network drop, not block) | INV-NETWORK-BACKPRESSURE-DROP-001 | Refined to distinguish network layer from timing layer | 2026-02-01 |
| RULE_HARVEST #8 (PTS from MasterClock) | INV-P10-PRODUCER-CT-AUTHORITATIVE | Clarified: producer provides CT; muxer uses it | 2026-02-01 |
| RULE_HARVEST #14 (drop if >2 frames behind) | INV-PACING-ENFORCEMENT-002 | Replaced by freeze-then-pad; no drops | 2026-02-01 |
| RULE_HARVEST #37 (<=33ms latency p95) | - | OBSOLETE: Phase 10 uses different metrics | 2026-02-01 |
| RULE_HARVEST #39 (3-tick backpressure) | RULE-P10-DECODE-GATE | Replaced by slot-based flow control | 2026-02-01 |
| RULE_HARVEST #45 (2-3 frame lead) | INV-P10-BUFFER-EQUILIBRIUM | Replaced by configurable buffer depth | 2026-02-01 |

---

## Demoted Rules

These rules remain documented but are no longer completion gates.

| Original Rule | Demoted To | Reason | Date |
|---------------|------------|--------|------|
| INV-SWITCH-READINESS (as completion gate) | Diagnostic goal | Switch completes at declared boundary time, not when readiness conditions met. Superseded by INV-SWITCH-DEADLINE-AUTHORITATIVE-001. | 2026-02-01 |
| INV-SWITCH-SUCCESSOR-EMISSION (as completion gate) | Diagnostic goal | Switch completes at declared boundary time, not when successor frame emitted. Superseded by INV-SWITCH-DEADLINE-AUTHORITATIVE-001. | 2026-02-01 |

---

## Reclassified Rules

These rules were reclassified to clarify their authority level.

| Rule | Original Classification | New Classification | Reason | Date |
|------|------------------------|-------------------|--------|------|
| INV-FRAME-001 | Authority | Execution precision | Frame-indexed boundaries describe execution precision, not decision authority. Clock decides WHEN; frames decide HOW. | 2026-02-01 |
| INV-FRAME-003 | Authority | Execution precision | CT derivation within segment does not gate switch execution. Frame completion does not delay clock-scheduled transitions. | 2026-02-01 |
| LAW-FRAME-EXECUTION | LAW | CONTRACT (subordinate) | Frame index governs execution precision within a segment. Subordinate to clock authority for transition timing. | 2026-02-01 |

---

## Absorbed Rules

These rules were absorbed into their parent rules during consolidation.

| Original Rule | Absorbed Into | Reason | Date |
|---------------|---------------|--------|------|
| INV-P8-TIME-BLINDNESS | INV-P8-006 | Duplicate of "producers do not read/compute CT" | 2026-02-01 |
| INV-P9-B-OUTPUT-LIVENESS | INV-P9-EMISSION-OBLIGATION | Renamed to avoid collision with LAW-OUTPUT-LIVENESS | 2026-02-01 |
| INV-CANONICAL-CONTENT-ONLY-001 | RULE-CANONICAL-GATING | Merged canonical asset rules | 2026-02-01 |

---

## Derivation Chains

Some superseded rules evolved through multiple iterations:

### Frame Execution Authority Chain

```
Original: INV-FRAME-001 (frames are authority)
    |
    v
Conflict: LAW-CLOCK (clock is authority)
    |
    v
Resolution: LAW-AUTHORITY-HIERARCHY (clock > frames)
    |
    v
Reclassified: INV-FRAME-001 (execution precision, not authority)
```

### Switch Completion Chain

```
Original: INV-SWITCH-READINESS (readiness gates completion)
    |
    v
Problem: Boundary timing violations when content not ready
    |
    v
Resolution: INV-SWITCH-DEADLINE-AUTHORITATIVE-001 (clock gates completion)
    |
    v
Demoted: INV-SWITCH-READINESS (diagnostic goal only)
```

### Flow Control Chain

```
Original: RULE_HARVEST #39 (3-tick backpressure)
    |
    v
Problem: Sawtooth stuttering with hysteresis
    |
    v
Resolution: RULE-P10-DECODE-GATE (slot-based gating)
    |
    v
Superseded: RULE_HARVEST #39
```

---

## Why Rules Get Retired

Rules are retired for several reasons:

1. **Conflict with Laws:** A rule conflicts with a Layer 0 law and must yield.

2. **Operational Experience:** Production incidents reveal that a rule causes more problems than it solves.

3. **Consolidation:** Multiple rules covering the same concept are merged into one authoritative rule.

4. **Scope Creep:** A rule originally designed for one purpose was being misapplied to another.

5. **Technology Evolution:** The underlying implementation changed, making the rule obsolete.

---

## Audit Trail

| Date | Action | Rules Affected | Audit Reference |
|------|--------|----------------|-----------------|
| 2026-02-01 | Superseded | RULE_HARVEST #3, #8, #14, #37, #39, #45 | CANONICAL_RULE_LEDGER audit |
| 2026-02-01 | Demoted | INV-SWITCH-READINESS, INV-SWITCH-SUCCESSOR-EMISSION | Authority Hierarchy amendment |
| 2026-02-01 | Reclassified | INV-FRAME-001, INV-FRAME-003, LAW-FRAME-EXECUTION | Authority Hierarchy amendment |
| 2026-02-01 | Absorbed | INV-P8-TIME-BLINDNESS, INV-P9-B-OUTPUT-LIVENESS, INV-CANONICAL-CONTENT-ONLY-001 | Consolidation pass |

---

## Cross-References

- [CANONICAL_RULE_LEDGER.md](../contracts/CANONICAL_RULE_LEDGER.md) - Superseded Rules section
- [BROADCAST_LAWS.md](../contracts/laws/BROADCAST_LAWS.md) - Derivation Notes section
