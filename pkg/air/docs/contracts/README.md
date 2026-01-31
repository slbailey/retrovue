# Contracts — Authority Model

This document defines the **authority model** of the documentation in this directory. It describes which documents are normative and which are informational, and how they relate. It does not list specific files or implementation details; it establishes the conceptual layers and rules that govern the system.

---

## Documentation Layers

Documentation is organized into six layers. Lower-numbered layers take precedence over higher-numbered ones when there is conflict.

### Layer 0 – Constitutional Laws

**Non-negotiable system guarantees.** These are the top-level invariants that define what the system *is*: clock authority, timeline ownership, output liveness, format guarantees, and switching behavior. They cannot be relaxed without changing the fundamental character of the playout engine. No other document may contradict them.

### Layer 1 – Semantic Contracts

**Correctness rules.** These specify truth about time, provenance, determinism, continuity, and output semantics. They define what “correct” means for timeline advancement, frame attribution, and emission guarantees. They are authoritative for behavioral correctness within their scope.

### Layer 2 – Coordination Contracts

**Concurrency, switching, backpressure.** These govern how components coordinate: write barriers, readiness, switching sequences, throttle and backpressure symmetry, and buffer equilibrium. They are authoritative for coordination and concurrency behavior within their scope.

### Layer 3 – Narrative / Design History

**Informational only.** Phase overviews, design rationale, and “what was built and why” live here. They provide context and history. They do not override laws or contracts; they explain intent and evolution.

### Layer 4 – Developer Notes / Investigations

**Informational only.** Ad-hoc notes, investigations, and working documents. Useful for understanding past decisions or current exploration. Not authoritative for behavior.

### Layer 5 – Archive

**Historical.** Superseded or retired material. Kept for traceability. Not authoritative.

---

## Authority Rules

These rules are binding for how documentation and code interact.

1. **Laws override all other documents.**  
   Constitutional laws (Layer 0) are supreme. No contract, phase document, or narrative may contradict them. If a lower-priority document conflicts with a law, the law wins.

2. **Contracts are authoritative within their layer.**  
   Semantic contracts (Layer 1) and coordination contracts (Layer 2) are normative within their respective domains. Implementation must satisfy them. Disagreement between code and contract is resolved in favor of the contract until the contract is explicitly changed.

3. **Phase and narrative documents are informational only.**  
   Layer 3 (and above) documents do not define required behavior. They inform; they do not override laws or contracts. They may describe intended design, but code and contracts are the source of truth for what the system actually guarantees.

4. **Code must conform to laws and contracts, not vice versa.**  
   When code and a law or contract conflict, the code is wrong. Fix the code or change the law/contract through the normal change process. Do not treat laws or contracts as advisory or “best effort.”

---

## Summary

| Layer | Name                     | Role                | Authority   |
|-------|--------------------------|----------------------|-------------|
| 0     | Constitutional Laws      | Non-negotiable guarantees | Supreme     |
| 1     | Semantic Contracts       | Correctness rules    | Normative   |
| 2     | Coordination Contracts   | Concurrency, switching, backpressure | Normative   |
| 3     | Narrative / Design History | Context and rationale | Informational |
| 4     | Developer Notes / Investigations | Working notes   | Informational |
| 5     | Archive                  | Retired material     | Historical  |

Laws and contracts (Layers 0–2) define what the system must do. Narrative and notes (Layers 3–5) explain and document; they do not override.

---

For indexes and entry points to specific contracts and invariants, see the other documents in this directory.
