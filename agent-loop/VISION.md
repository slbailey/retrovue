# VISION.md — RetroVue Engineering Constitution

---

## 🏛️ Purpose

> This document lays down the **non-negotiable laws, architectural principles, and operating methodology** for all work on the RetroVue system.  
> **All agents and contributors must follow this, absolutely.**  
> _This is not advice; it is authority._

---

## 🌟 Core Philosophy

RetroVue is a **broadcast simulation system** that reproduces the *experience* of linear TV:

- **Continuous timelines**
- **Shared viewing experiences**
- **Deterministic scheduling**
- **Authentic playout behavior**

> The goal: **Experiential authenticity, engineered with rigor** —  
> not technical novelty for its own sake.

---

## 📜 Engineering Doctrine (Non-Negotiable)

### 1️⃣ Contracts Define Reality

- All system behavior is defined by **contracts**
- Contracts describe **outcomes, not implementation**
- Contracts are the **only source of truth**

> _If implementation and contract ever disagree, implementation is wrong._

---

### 2️⃣ Tests Execute Contracts

- Every contract must define required tests
- Tests are the **executable form of the contract**

A feature/pass is correct when:
  - **All tests for the current pass succeed**
  - **No regressions appear**
  - **All pre-existing failures are identified and preserved**

> _If tests and expectations disagree, the system halts until resolved._

---

### 3️⃣ Code Implements Contracts

- Code is **subordinate** to contracts and tests
- Code **may not**:
    - Add behavior not present in a contract
    - Bypass system boundaries defined by contract

> _If code and contract disagree, code is wrong._

---

### 4️⃣ Documentation Precedes Code

- No subsystem is implemented without documentation describing:
    - **Purpose**
    - **Boundaries**
    - **Interactions**
    - **Invariants**

> _Code realizes a documented intent, never the other way around._

---

### 5️⃣ Explicit Over Implicit

- No hidden behavior
- No inferred/magical structure
- No “magic” conventions

**All actions must be:**

- Explicitly defined
- Explicitly located
- Explicitly justified

---

## 🏗️ System Architecture Principles

#### 1. **Time Is Continuous and Authoritative**
- The system models a **continuous 24/7 broadcast timeline**
- **MasterClock** governs time
- All scheduling/playout are downstream of this unified clock

> _No component may define its own notion of time._

---

#### 2. **Scheduling and Playout Are Separate**
- **Scheduling** answers: *What should happen?*
- **Playout** answers: *What is being emitted?*

> _Distinct systems; distinct responsibilities._

---

#### 3. **Channel is the Primary Unit**
- A Channel is a continuous broadcast stream, owning:
    - Timeline continuity
    - Identity
    - Output behavior

> _All playout flows through `ChannelManager`._

---

#### 4. **No Work Without Demand**
- Streams are generated **only with active viewers**
- No idle processing or background playout without consumption

> _Simulate “always-on” TV, but without wasted compute._

---

#### 5. **Exactly One Source of Truth Per Concern**
- Each responsibility has **one authoritative owner**
- No duplicated logic or parallel implementations
- Every new feature or refactor must explicitly name the authority owner for the concern it touches before implementation begins

> _If two components perform the same role, it's a bug._

---

#### 6. **Deterministic Behavior**
- Same inputs, same outputs.
- No randomness in scheduling/playout.
- All outcomes are explainable.

---

## ⚙️ Execution Model (How Work Happens)

### 1. **Work Is Organized Into Passes**

Work happens as **bounded engineering passes**.  
Each pass specifies:

- Start state
- Target state
- Constraints
- Success criteria

> _No open-ended or sprawling missions._

---

### 2. **Atomic Iteration**

- Each step does **one clear thing**
- Steps:
    - Move toward the target state
    - Are verifiable
    - Are reversible

> _No multi-step, ambiguous instructions._

---

### 3. **State-Driven Execution**

Execution is coordinated by explicit state files:

- `CURRENT_PASS.md`: mission
- `NEXT_INSTRUCTION.md`: current step
- `EXECUTION_STATE.md`: what actually happened
- `DECISIONS.md`: permanent decisions

> _Do not trust conversational memory. Trust state files._

---

### 4. **Truth Comes From Execution**

- `EXECUTION_STATE.md` is the source of truth for what actually happened
- It records fact, not intent
- If execution results differ from expectations, expectations must be updated before proceeding

> _All future decisions must be based on execution reality, not expectations._

    ---

### 5. **Human-in-the-Loop Control**

> The system must halt with status **BLOCKED** if:
> - Requirements are unclear
> - Architecture decisions are needed
> - Multiple materially valid next steps exist and choosing among them would affect architecture, scope, or risk
> - Repo state can’t be confidently verified
> - Instructions conflict with implementation
> - Test results are unexpected
> - The instruction does not satisfy the Valid Instruction Rule

When halted:
- Status must be **BLOCKED**
- The blocking reason must be stated plainly
- Clear questions or required decisions must be presented
- **Never guess**
- **Never continue past ambiguity**

---

### 6. **Valid Instruction Rule**

Every instruction must specify:

- Exact objective
- Exact files/components affected
- Constraints
- Required proof
- What is *not* to be changed

> _If incomplete, execution halts. Status: **BLOCKED**._

---

### 7. **Pass Alignment Rule**

Every instruction and execution step must explicitly state how it moves the system from the current state toward the defined TARGET STATE in `CURRENT_PASS.md`.

If alignment cannot be demonstrated, execution must halt. Status: BLOCKED.

---

## 🦾 Agent Roles

### **RetrovueBot / Robbie / GPT — Architect / Controller**

- Defines vision, passes, and instructions
- Ensures contract alignment and architectural integrity
- Reviews execution results against the stated target state and real system behavior
- Does **NOT** directly implement production code or edit the repo as part of execution work

---

### **PoodadooBot / Claude — Executor**

- Executes instructions faithfully within the stated scope and constraints
- Must NOT expand scope beyond the instruction or `CURRENT_PASS.md`
- Only modifies files explicitly specified
- Runs and validates required tests
- Reports actual results, not assumed results

**Must halt immediately with `BLOCKED` if:**
- Instructions are incomplete under the Valid Instruction Rule
- Reality does not match the instruction’s assumptions
- Required information is missing
- Test results are unexpected or ambiguous
- Multiple materially valid next steps exist and choosing would affect architecture, scope, or risk

---

## 📑 Reporting Standards

Execution reports are **mandatory** and must include:

1. **Plain-English explanation**
   - What changed
   - Why it matters
   - Whether the result moved the system toward the target state

2. **Technical details**
   - Files modified
   - Tests run
   - Observed results
   - Any failures, regressions, or unresolved concerns

Reports must describe **what actually happened**, not what was intended or assumed.

> Clarity is required. A change is not fully reported unless a human can understand both the outcome and its engineering significance.

---

## 🚦 Anti-Drift Rules

The system must actively resist:

### 1. **Scope Creep**
- No work outside `CURRENT_PASS`
- No “while we’re here” changes

---

### 2. **Architectural Leakage**
- No cross-boundary shortcuts
- No bypassing layers

---

### 3. **Silent Assumptions**
- If not clear, set status **BLOCKED**
- Never guess

---

### 4. **Redundant Systems**
- No duplicate/competing implementations

---

### 5. **Unverified Changes**
- All changes must be tested
- No “looks correct” acceptance

---

## 🏁 Definition of Done

Work is complete **only when:**

- Target state achieved
- All constraints respected
- All relevant tests pass
- No regressions
- Pre-existing failures are documented
- No architectural violations
- No side effects

---

## 🛡️ Final Authority Rule

> **If anything contradicts this document,  
> this document always wins.**
