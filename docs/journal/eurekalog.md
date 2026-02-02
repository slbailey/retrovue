## 🏛️ Authority Insight
- **Bug:** Viewer disconnect caused encoder deadlock  
- **Why local fix failed:** Encoder/audio buffering was **not** the root cause  
- **Insight:** Teardown authority conflicted with time-authoritative playout  
- **New Rule:** _Lifecycle authority must be explicit and negotiated_

---

## 🔺 Phase Escalation
- **Bug:** Teardown during SwitchToLive caused orphaned AIR
- **Why local fix failed:** Ad-hoc teardown delays still violated invariants
- **Insight:** Not a bug, but a missing architectural phase
- **New Phase:** _Live Session Authority & Teardown Semantics (Phase 12)_

---

## 🛡️ Invariant Birth
- **Bug:** Channel destroyed in `SWITCH_ISSUED` state
- **Why local fix failed:** `SWITCH_ISSUED` treated as “almost live”
- **Insight:** Transient states are fundamentally _unsafe_ for teardown
- **New Invariant:** `INV-TEARDOWN-STABLE-STATE-001`

---

## 🧮 Model Correction
- **Assumption:** `viewer_count == 0` ⇒ teardown is always safe
- **Contradiction:** Viewer disconnect during transient boundary _broke system_
- **Insight:** Viewer count is a _local signal_, not global authority
- **New Rule:** Viewer count is _advisory_ during transient states  
- **Invariant:** `INV-VIEWER-COUNT-ADVISORY-001`

---

## ✳️ Semantic Clarification
- **Ambiguity:** When is a channel actually _“live”_?
- **Failure:** Code assumed liveness before AIR confirmation
- **Insight:** “Live” must be a **durable, authority-backed** state
- **New Rule:** Channel is _durably live only when_ `boundary_state == LIVE`
- **Invariant:** `INV-LIVE-SESSION-AUTHORITY-001`

---

## 💥 Failure Taxonomy
- **Observation:** Teardown failure caused encoder deadlock, audio overflow, pad storms  
- **Insight:** These are _predictable outcomes_ of transient-state teardown  
- **New Concept:** _Stable vs transient lifecycle states_  
- **Codified:** Phase 12 §4 (Boundary State Classification)

---

## ⏳ Timeout Justification
- **Q:** Why _not_ wait indefinitely for transition completion?
- **Insight:** Indefinite deferral causes zombie channels & resource leaks
- **New Rule:** Deferred teardown _must be bounded in time_
- **Invariant:** `INV-TEARDOWN-GRACE-TIMEOUT-001`

---

## 🎛️ Control-Plane Discipline
- **Bug Pattern:** Teardown triggered while new work still scheduled
- **Insight:** Deferral _without work suppression_ prolongs instability
- **New Rule:** _No new boundary work while teardown is pending_
- **Invariant:** `INV-TEARDOWN-NO-NEW-WORK-001`

---

## 🤖 AI Rejection
- **AI Suggestion:** Tweak buffer sizes / add sleeps / delay teardown
- **Reason Rejected:** Violates lifecycle authority, treats symptom not cause
- **Insight:** AI optimizes _locally_ unless _constrained by contracts_
- **New Practice:** Promote reasoning failures _into invariants, not patches_

---

## 🔍 Method Insight
- **Observation:** Bugs resolved _cleanly_ only after invariant formalization
- **Insight:** Tests enforce behavior, contracts enforce meaning
- **New Practice:** Treat _invariants as law_, tests as enforcement

---

## 🧭 Workflow Realization
- **Observation:** AI performed best when intent was _frozen_
- **Insight:** AI is _good at satisfying constraints, bad at inventing them_
- **New Workflow:** _Contracts first, AI second, tests as referee_

---

## 🔮 Predictive Validation
- **Observation:** Phase 12 §4.3 failure modes _matched incident exactly_
- **Insight:** Good architecture _predicts failures before they happen_
- **Conclusion:** _Phase-based contract design scales better_ than patching


[Method Breakthrough]
Observation: passing time metadata across Core → gRPC → AIR would normally take weeks to debug
Why it was faster: lifecycle contracts and invariants narrowed the problem to authority violations
Insight: AI accelerates dramatically when the problem is classification, not exploration
Conclusion: structure converts AI from guesser into executor

[Failure Containment Insight]
Observation: after FAILED_TERMINAL, scheduler still attempted LoadPreview and switch scheduling
Insight: terminal boundary must absorb all scheduling intent, not just transitions
New rule: FAILED_TERMINAL short-circuits tick() and planning paths
Outcome: terminal failure becomes contained, not noisy
