# Invariant House Style Specification

Extracted from existing documents under `docs/contracts/`. No invention; mirrors current practice exactly.

This document is used to generate new invariants and laws that conform to established conventions.

---

## 1. Document Taxonomy

Two document classes exist, with distinct authority levels:

| Class | Prefix | Location | Purpose |
|---|---|---|---|
| **Law** | `LAW-` | `docs/contracts/laws/` | Constitutional principles. Highest authority. Abstract, non-testable directly. |
| **Invariant** | `INV-` | `docs/contracts/invariants/{air,core,shared,sink}/` | Concrete behavioral guarantees. Testable. Derive from laws. |

Invariants are filed by ownership domain:
- `air/` — AIR-owned runtime execution invariants
- `core/` — Core-owned orchestration invariants
- `shared/` — Cross-cutting invariants spanning both components
- `sink/` — Sink/mux-specific output invariants

---

## 2. Naming Conventions

**Invariants:**
- Format: `INV-KEBAB-CASE` or `INV-KEBAB-CASE-NNN`
- The name is a terse behavioral descriptor, not a component name
- Numeric suffix (`-001`) is optional; used when a family of related invariants may exist
- Optional parenthetical subtitle after the ID on the H1 line: `# INV-PAD-PRODUCER (Content-before-pad gate)`

**Laws:**
- Format: `LAW-SINGLE-WORD` or `LAW-KEBAB-CASE`
- Name captures the constitutional domain (CLOCK, LIVENESS, SWITCHING, etc.)

---

## 3. File Naming

Filename matches the document ID exactly, with `.md` extension:
- `INV-BACKPRESSURE-SYMMETRIC.md`
- `LAW-CLOCK.md`

---

## 4. Invariant Section Structure (Canonical Order)

```markdown
# INV-NAME-HERE

## Behavioral Guarantee
<what the system guarantees>

## Authority Model
<who/what owns and enforces this guarantee>

## Boundary / Constraint
<the precise rule, using MUST/MUST NOT>

## Violation
<what constitutes a violation>

## Derives From          ← optional; present when explicitly tracing to a law

## Required Tests
- <bullet list of test file paths>

## Enforcement Evidence
TODO
```

**Optional elements observed:**
- `**Owner:** AIR` — bold owner tag between H1 and first section (seen in INV-PAD-PRODUCER only)
- `## Derives From` — explicit upward traceability to a law (seen in INV-TIME-MODE-EQUIVALENCE-001 only)

**Enforcement Evidence** is always `TODO` in current corpus. The section exists as a placeholder for future runtime evidence linkage.

---

## 5. Law Section Structure (Canonical Order)

```markdown
# LAW-NAME-HERE

## Constitutional Principle
<absolute statement of the law, 1-3 sentences>

## Implications
- <bullet list of derived consequences>

## Violation
<what constitutes violation of this law>
```

Laws have no test references, no enforcement evidence section, and no authority model section. They are self-authoritative.

---

## 6. Modal Language

Follows RFC 2119 conventions, always uppercased:
- **MUST** — mandatory requirement
- **MUST NOT** — absolute prohibition
- No instances of SHOULD, MAY, or RECOMMENDED in the corpus

Every constraint is absolute. There is no hedging or conditional language.

---

## 7. Tone and Voice

- **Declarative, present tense.** States what *is* guaranteed, not what *should* be.
- **Internal spec register.** No audience-facing explanation or rationale.
- **No preamble or introduction.** Sections begin immediately with the rule.
- **Terse.** Most sections are 1-3 sentences. No paragraph-length prose.
- **Impersonal.** No "we", "you", or "the team". Subjects are system components.
- **No rationale sections.** The *why* is not documented; only the *what* and *what constitutes violation*.

Examples of characteristic phrasing:
- "Audio samples MUST NOT be discarded as a result of queue overflow, congestion, or backpressure."
- "No subsystem may invent, reset, or locally reinterpret time."
- "Pad MUST be available and format-conforming."
- "Emission MUST NOT be triggered by frame availability alone."

---

## 8. Behavioral Guarantee Section Style

- Opens with the core guarantee as a declarative statement.
- May be a single sentence or 2-3 short sentences.
- Uses MUST/MUST NOT for the binding rule.
- Sometimes includes a secondary condition or scope clarification.

---

## 9. Authority Model Section Style

- Identifies the owner of the guarantee (component, mechanism, or design element).
- Short — typically one sentence.
- Does not explain *how* enforcement works; only *who* is responsible.
- Examples: "Mux loop is the sole pacing authority." / "Audio path and backpressure design own this guarantee."

---

## 10. Boundary / Constraint Section Style

- Restates the guarantee as a precise, testable constraint.
- Uses MUST/MUST NOT.
- Often more specific than Behavioral Guarantee (adds thresholds, timing bounds, conditions).
- May include parenthetical examples: "(e.g. emission within 500ms window)"

---

## 11. Violation Section Style

- Describes the observable condition that constitutes violation.
- Often the logical negation of the guarantee.
- May include "MUST be logged" directive when runtime detection is expected.
- Short — 1-2 sentences or a semicolon-separated list of violation conditions.

---

## 12. Required Tests Section Style

- Bullet list.
- Each bullet is a relative path from repo root to the test file.
- Specific test names in parentheses when relevant: `(TEST_INV_P10_BACKPRESSURE_SYMMETRIC_NoAudioDrops)`
- Test IDs may appear inline: `TS-EMISSION-001: first TS within bound after attach`
- Mix of C++ (`.cpp`) and Python (`.py`) test references.

---

## 13. Cross-Reference Formatting

- Other invariants and laws referenced by backtick-quoted ID: `LAW-CLOCK`, `INV-DECODE-GATE`
- No hyperlinks. No path references for cross-document links.
- Upward traceability (invariant → law) via `## Derives From` section when present.

---

## 14. Prohibitions (What Is NOT Done)

- No version fields or changelog sections.
- No date stamps.
- No author attribution (except the rare `**Owner:**` tag).
- No priority or severity fields.
- No status field (active/deprecated).
- No rationale or motivation sections.
- No examples section.
- No prose paragraphs longer than 3 sentences.
- No SHOULD/MAY language.

---

## 15. Summary Table

| Attribute | Invariant (playout) | Invariant (scheduling / constitutional) | Law |
|---|---|---|---|
| Prefix | `INV-` | `INV-` | `LAW-` |
| H1 | ID (optional parenthetical subtitle) | `ID — Title` | ID |
| Metadata header | None | Status / Authority Level / Derived From | None |
| Sections | Behavioral Guarantee → Authority Model → Boundary/Constraint → Violation → [Derives From] → Required Tests → Enforcement Evidence | Purpose → Guarantee → Preconditions → Observability → Deterministic Testability → Failure Semantics → Required Tests → Enforcement Evidence | Constitutional Principle → Implications → Violation |
| Test refs | Yes (bullet paths) | Yes (bullet paths) | No |
| Modal verbs | MUST / MUST NOT | MUST / MUST NOT | MUST / MUST NOT + lowercase declarative |
| Enforcement Evidence | Always present (TODO) | Always present (TODO) | Not present |
| Tone | Terse declarative spec | Constitutional, outcome-focused | Terse constitutional declaration |
| Length | 15-50 lines | 30-70 lines | 15-28 lines |

---

## 16. Constitutional Invariant Format (Scheduling Domain)

Scheduling invariants use an extended format to satisfy three additional requirements:

1. **Law anchor traceability** — every invariant names its governing laws.
2. **Failure classification** — violations are classified as Planning fault, Runtime fault, or Operator fault.
3. **Deterministic testability** — invariants explicitly state how they can be tested without real-time waits.

```markdown
# INV-<NAME>-NNN — <Short title>

Status: Invariant
Authority Level: <Planning | Runtime | Cross-layer>
Derived From: `LAW-XXX`, `LAW-YYY`

## Purpose
<One paragraph: what constitutional risk this protects. Names the laws at risk.>

## Guarantee
<Precise, falsifiable statement. Uses MUST / MUST NOT.>

## Preconditions
<Conditions that must hold for this invariant to apply. Omit section if none.>

## Observability
<How a violation is detected at runtime or audit time.>

## Deterministic Testability
<How to validate without real-time waits. Concrete scenario description.>

## Failure Semantics
<Planning fault | Runtime fault | Operator fault — and brief explanation.>

## Required Tests
- <bullet paths>

## Enforcement Evidence
TODO
```

**Guardrails:**
- Every invariant MUST name at least one law in `Derived From`. An invariant with no law anchor does not belong.
- Invariants protect **outcomes**, not mechanisms. Do not specify call sequences or implementation steps.
- Layer purity: SchedulePlan invariants do not mention Playlog; ScheduleDay invariants do not mention ChannelManager; Playlog invariants reference SchedulePlan only in derivation context.
