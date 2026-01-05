_Related: [Development roadmap](development-roadmap.md) • [Architecture overview](../architecture/ArchitectureOverview.md) • [Plugin authoring](PluginAuthoring.md)_

# RetroVue Engineering Design Principles

## Overview

This document establishes the architectural foundation for RetroVue development. It defines **how** code must be written, not what the system does functionally.

### Purpose

RetroVue is not a simple script—it's a sophisticated 24/7 broadcast simulation system with multiple services, real-time timing, and complex state management. This requires disciplined architecture to remain maintainable and extensible.

**This document prevents unstructured "just make it work" code from entering the system.**

### The Gatekeeper Rule

Before adding any new component, service, manager, worker, or subsystem:

1. **You must identify which design principle(s) it follows**
2. **If you cannot, you must evolve these principles first**
3. **Nothing "temporary" is allowed to harden into production**

This document is the architectural gatekeeper. It may evolve, but all changes must be intentional and documented.

## Why These Principles Exist

### The Challenge

We are building a complex system that must:

- Simulate continuous 24/7 broadcast operations
- Manage multiple concurrent services
- Handle real-time timing requirements
- Support future extensibility
- Maintain system integrity under various conditions

### What This Requires

- **Modular code** with clear boundaries
- **Single-purpose components** with well-defined responsibilities
- **Replaceable parts** that don't require system-wide rewrites
- **Debuggable architecture** where failures are isolated and traceable

### What We Prevent

This document stops these anti-patterns:

- _"I jammed ffmpeg calls inline in this request handler because I needed output"_
- _"The scheduler now also does ingest because it was easier"_
- _"I copied logic from somewhere else and tweaked it until it worked"_

**This is our defense against architectural debt and glue code.**

## Component Requirements

Every component in RetroVue—from high-level orchestrators to low-level workers, internal services, and helpers—must satisfy these three fundamental requirements:

### 1. Single Responsibility

**Every component has one clear, named purpose.**

- If you cannot summarize what it does in one sentence, it's too complex
- Each component should have a focused, well-defined job
- Multiple responsibilities indicate the need for decomposition

### 2. Pattern Compliance

**Every component fits a recognized architectural pattern.**

- No free-floating procedural code blobs
- Components must be clearly identifiable as: "this is an Adapter," "this is an Enricher," "this is an Infrastructure service," "this is an Orchestrator," etc.
- If it doesn't fit a known pattern, we must define a new one

### 3. Replaceability

**Every component can be swapped out without system-wide changes.**

- Can you unplug this component and plug in another implementation?
- Does the component have clear interfaces and dependencies?
- Can it be tested in isolation?

**These are non-negotiable requirements. Violations constitute architectural debt by definition.**

## Core Architectural Patterns

These patterns form the building blocks of RetroVue's architecture. Not every component uses all patterns, but every component must be explainable in terms of at least one.

### Pattern Categories

We organize patterns into two fundamental categories:

1. **Boundary / Dataflow Patterns** - Govern how information moves into, through, and out of the system
2. **Behavioral / Structural Patterns** - Govern how internal components behave once data is in the system

## Boundary / Dataflow Patterns

These patterns control the flow of information across system boundaries and ensure proper data transformation and persistence.

### Adapter

**Purpose:** Boundary between RetroVue and external systems

**What it does:**

- Translates external data formats into internal representations
- Provides a consistent interface to external systems
- Isolates external system quirks from core logic

**Why it exists:**
External systems are opinionated, inconsistent, and will change. We don't let that complexity leak into our core system.

**Rules:**

- **External Communication Only:** Adapters talk to "not us" (external systems)
- **Normalization:** Convert external representations into known internal contracts
- **No Business Logic:** Adapters don't persist state, enforce policy, or schedule operations
- **Translation Only:** They can feed Importers/Enrichers, but remain "translation, not commitment"

**Violation Smell:**
If core logic suddenly knows Plex's quirks, filesystem layouts, or ffmpeg CLI flags, you skipped an Adapter.

### Importer

**Purpose:** Commits normalized data to RetroVue's authoritative state

**What it does:**

- Takes normalized data from Adapters/Enrichers
- Makes data "real" within the RetroVue system
- Ensures data integrity through transactional boundaries

**Why it exists:**
There is a critical moment where external data becomes "real" to RetroVue. We make this moment explicit and controlled.

**Rules:**

- **Persistence Required:** Importers must persist data to authoritative storage
- **Transactional Boundaries:** Must run within a Unit of Work
- **Atomic Operations:** Either fully commit or fully rollback—no partial states
- **Truth Recording:** They record facts, not policy decisions (e.g., "should we use this at 8PM?")

**Violation Smell:**
If you see direct writes to internal state scattered throughout the codebase "just to get something in," you skipped the Importer and destroyed auditability.

### Enricher

**Purpose:** Adds derived meaning and semantics to raw data

**What it does:**

- Augments entities with structured metadata and classifications
- Adds business meaning that external systems don't provide
- Creates consistent, structured representations from raw data

**Why it exists:**
"Raw file" is almost never "usable object." We add semantics so the rest of the system doesn't have to guess or infer meaning.

**Rules:**

- **Deterministic:** Same input always produces the same output meaning
- **Structured Metadata:** Adds flags, tags, roles, classifications, breakpoints, restrictions, etc.
- **Annotation Only:** Enrichers don't persist final authority—they annotate (Importers commit the enriched form)
- **No Policy Decisions:** They add meaning, not business rules

**Violation Smell:**
If downstream logic is trying to infer meaning ("I guess this is probably safe for daytime?"), you skipped enrichment and spread interpretation throughout the system.

### Unit of Work (UoW)

**Purpose:** Ensures atomic operations that either fully succeed or fully fail

**What it does:**

- Defines atomic boundaries around meaningful system operations
- Guarantees consistency by ensuring all-or-nothing execution
- Prevents partial system states that are impossible to reason about

**Why it exists:**
Half-finished operations are unacceptable in a 24/7 broadcast system. Not for ingest, plan generation, or mode changes.

**Rules:**

- **Single Station-Level Action:** Each UoW represents one meaningful system operation (e.g., "import this batch," "extend schedule horizon," "switch operating mode")
- **Atomic Execution:** Everything inside either completes together or rolls back completely
- **Explicit Coordination:** UoW is not a helper—it's a coordination boundary that must be explicit in code
- **No Partial States:** No "kinda half-done" states are allowed

**Violation Smell:**
If you're doing "I updated some records and started some processes and maybe logged something, and if step 3 failed we're kinda half-done," you skipped a UoW and created an unrecoverable ghost state.

## Behavioral / Structural Patterns

These patterns govern how internal components behave once data is in the system.

### Orchestrator

**Purpose:** Coordinates multiple components to perform complex, multi-step operations

**What it does:**

- Coordinates other components to achieve higher-level behaviors
- Manages the sequence and flow of complex operations
- Acts as a conductor, not a worker

**Examples in spirit:**

- Channel supervision systems
- Emergency mode activation
- Schedule horizon management
- System state transitions
- **ScheduleOrchestrator** - Orchestrator for generating timelines
- **ProgramManager** - System-level Orchestrator + policy enforcement
- **ChannelManager** - Per-channel Orchestrator

**Why it exists:**
Complex actions require multiple steps that may cross system boundaries. We need a conductor that knows the proper sequence and calls the right services.

**Rules:**

- **Coordination Only:** Orchestrators call other components; they don't reach into raw infrastructure
- **No Direct Mutation:** Don't mutate data stores directly unless within a declared Unit of Work
- **Work Coordination:** They don't "do the work"—they line up and coordinate work
- **Clear Boundaries:** Each step should be delegated to appropriate specialized components

**Violation Smell:**
If you have a module that decides policy, executes ffmpeg commands, writes to storage, updates counters, and sends network signals—that's five jobs. You built a god object instead of an Orchestrator with proper collaborators.

### Service / Capability Provider

**Purpose:** Provides focused, reusable capabilities to the rest of the system

**What it does:**

- Exposes a single, well-defined capability at runtime
- Provides consistent interfaces for common system needs
- Encapsulates infrastructure concerns behind clean interfaces

**Examples:**

- Time authority and scheduling
- Stream output management
- Persistence gateway operations
- Metrics collection and reporting
- ID generation and validation
- Configuration management
- **Producer** - Capability Provider for actual output, forbidden from policy decisions

**Philosophy:** "I do one thing, clearly, on demand, and I do it well."

**Why it exists:**
We don't want ad hoc logic scattered throughout call sites. We want clear, testable capabilities that other code can depend on, mock, and replace.

**Rules:**

- **Well-Defined Interface:** Clear contract ("ask me for X, I'll give you Y")
- **Single Responsibility:** Does NOT orchestrate multi-step flows—does its one job
- **Testable:** Must be mockable in tests
- **Infrastructure Encapsulation:** Hides low-level details from business logic

**Violation Smell:**
If random parts of the code are doing `datetime.now()` or spawning subprocesses inline "because it was easier," you skipped a Service and leaked infrastructure concerns into business logic.

### Authority

**Purpose:** Single source of truth for specific categories of system state

**What it is:**
An Authority is the sole owner and definer of a particular category of truth within the system.

**Critical Rule:** If something is an Authority, nothing else is allowed to re-infer, shadow, override, silently cache, or "just recompute" that truth.

**Why it exists:**
Disagreement kills reproducibility. If two parts of the system disagree on "what's true right now," you cannot answer "what happened" later.

**Examples in RetroVue:**

- **ScheduleService** - Authority for future timeline
- **MasterClock** - Authority for time

**Rules:**

- **Single Source:** Only one component in the system can define a given kind of truth
- **Mandatory Consultation:** Everything else must consult that component instead of rebuilding truth locally
- **Architectural Significance:** Introducing a new Authority is a major architectural decision and must be reflected in this document
- **No Duplication:** No shadow authorities, cached versions, or local recomputations

**The Service/Authority Firewall:**

A Service is allowed to answer questions or perform work. An Authority is allowed to define truth. Do not silently let a Service become an Authority "because everything already calls it." If something is promoted to Authority, that promotion must be written into this document.

**Violation Smell:**
If you see multiple places guessing "current time," "current mode," or "current plan," you've destroyed system determinism and created unreconcilable state conflicts.

## Architectural Pattern Overview

The following diagram illustrates how these patterns work together in RetroVue's architecture:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           RetroVue Architecture                            │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  External Systems    │  Boundary Patterns    │  Behavioral Patterns         │
│  ────────────────    │  ──────────────────   │  ──────────────────────      │
│                       │                       │                              │
│  ┌─────────────┐     │  ┌─────────────┐     │  ┌─────────────────────┐     │
│  │   Plex      │────▶│  │   Adapter   │────▶│  │   Orchestrator      │     │
│  └─────────────┘     │  └─────────────┘     │  └─────────────────────┘     │
│                       │         │             │             │               │
│  ┌─────────────┐     │         ▼             │             ▼               │
│  │  FileSystem │────▶│  ┌─────────────┐     │  ┌─────────────────────┐     │
│  └─────────────┘     │  │   Enricher  │     │  │     Service         │     │
│                       │  └─────────────┘     │  └─────────────────────┘     │
│  ┌─────────────┐     │         │             │             │               │
│  │   ErsatzTV  │────▶│         ▼             │             ▼               │
│  └─────────────┘     │  ┌─────────────┐     │  ┌─────────────────────┐     │
│                       │  │   Importer │     │  │     Authority       │     │
│                       │  └─────────────┘     │  └─────────────────────┘     │
│                       │         │             │                              │
│                       │         ▼             │                              │
│                       │  ┌─────────────┐     │                              │
│                       │  │ Unit of Work│     │                              │
│                       │  └─────────────┘     │                              │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

**Data Flow:**

1. **External Systems** → **Adapters** (translate external formats)
2. **Adapters** → **Enrichers** (add business meaning)
3. **Enrichers** → **Importers** (commit to authoritative state)
4. **Importers** → **Unit of Work** (ensure atomicity)
5. **Orchestrators** coordinate the flow
6. **Services** provide capabilities
7. **Authorities** maintain single sources of truth

## Prohibited Practices

These practices are **non-negotiable**. If you see these in code review, you must stop them immediately.

### 1. God Objects

**What it is:** A single component that handles multiple unrelated responsibilities

**Examples:**

- A module that ingests data, enriches it, persists it, makes policy decisions, spawns processes, and answers runtime queries
- Components that grow to handle "everything related to X"

**Why it's forbidden:** God objects are untestable, non-replaceable, and violate single responsibility principles.

### 2. Inline Side-Effect Soup

**What it is:** Multiple unrelated side effects in a single function without proper boundaries

**Examples:**

- Spawning a process, mutating DB state, emitting events, and logging in the same function
- Random functions that do "a little bit of everything"

**Why it's forbidden:** Creates unpredictable behavior and makes debugging impossible.

**Solution:** If the operation is meaningful, wrap it in a Unit of Work. If it's mechanical, move it to Infrastructure.

### 3. Authority Bypass

**What it is:** Circumventing the single source of truth

**Examples:**

- "I just cached the current state locally because calling the official source was annoying"
- Local recomputation of authoritative data
- Shadow authorities or duplicate truth sources

**Why it's forbidden:** Creates system forks and destroys determinism.

**Solution:** If there's an Authority, you must consult it. No exceptions.

### 4. External Assumptions in Core Logic

**What it is:** Core logic that knows external system details

**Examples:**

- Core logic knowing "Plex stores ratings like XYZ"
- Business logic understanding "this file path layout always means commercial"
- Internal code making assumptions about external system quirks

**Why it's forbidden:** Violates the boundary that Adapters exist to protect.

**Solution:** Move external knowledge to Adapters.

### 5. Inline Infrastructure Calls

**What it is:** Direct infrastructure calls in high-level logic

**Examples:**

- "Just call the shell here"
- Direct ffmpeg invocations in business logic
- Socket writes and IO operations in orchestration code

**Why it's forbidden:** Breaks replaceability and testing.

**Solution:** Encapsulate infrastructure in Services.

## The Golden Rule

**You are never allowed to duct-tape behavior in-place "just to get it working."**

**You must express it in terms of one of the patterns above.**

**If no existing pattern fits, you must propose a new pattern for this document. We do not silently invent one-off hacks in production code.**

## Implementation Guide for New Developers

When you're about to build something new, follow this decision tree to identify the correct architectural pattern:

### Step 1: Identify Your Component's Role

Ask yourself these questions in order:

**Are you translating from an external system → our internal world?**
→ **Adapter** - You're bridging external systems with RetroVue

**Are you committing something to authoritative state?**
→ **Importer** (under a Unit of Work) - You're making data "real" in the system

**Are you deriving structured meaning from raw data?**
→ **Enricher** - You're adding business semantics and metadata

**Are you coordinating multiple steps to perform a meaningful system action?**
→ **Orchestrator** - You're conducting a complex multi-step operation

**Are you exposing a focused capability the rest of the system needs?**
→ **Service / Capability Provider** - You're providing a specific, reusable capability

**Are you the canonical owner of some truth the rest of the system depends on?**
→ **Authority** - You're the single source of truth for something

### Step 2: Apply Safety Boundaries

**Wrap in Unit of Work if needed:**

- If the action is meaningful ("ingest batch," "promote system state," "roll horizon forward")
- If it must either fully happen or not happen at all
- If partial completion would create an inconsistent state

**Encapsulate Infrastructure:**

- Put IO and OS-level work in Infrastructure services
- High-level logic should ask for outcomes, not manually open sockets or fork processes
- Keep infrastructure concerns separate from business logic

### Step 3: Handle Edge Cases

**If it doesn't fit any existing pattern:**

1. **Stop and document** - Don't just ship it
2. **Propose a new pattern** - Explain why it needs to exist
3. **Get architectural approval** - Add it to this document
4. **Then build to that pattern** - Don't invent one-off hacks

### Decision Flowchart

```
New Component Needed
        ↓
External System Integration?
    ↓ Yes                    ↓ No
Adapter                 Internal System Logic?
                        ↓ Yes
                    State Change?
                    ↓ Yes        ↓ No
                Importer      Data Processing?
                            ↓ Yes        ↓ No
                        Enricher    Coordination?
                                    ↓ Yes        ↓ No
                                Orchestrator  Capability?
                                            ↓ Yes        ↓ No
                                        Service    Authority?
                                                ↓ Yes
                                            Authority
```

## Summary

This document exists to **enforce architectural intent** and prevent technical debt from accumulating in RetroVue.

### Our Core Beliefs

- **Clear Boundaries** - Adapter / Importer / Enricher patterns create clean separation of concerns
- **Safe Operations** - Unit of Work ensures atomic, consistent system changes
- **Clean Layering** - Infrastructure vs Orchestrator vs Service creates maintainable abstractions
- **Single Sources of Truth** - Authority pattern prevents system forks and inconsistencies
- **Replaceability and Testability** - Over "it works if you don't touch it"

### What This Means in Practice

**Not every component will look the same.** A Producer isn't an Importer. A clock service isn't an Enricher. That's perfectly fine.

**What is not fine:**

> "Here's a blob of procedural code we stapled together because we needed a demo."

### The Final Rule

**Every meaningful piece of functionality in RetroVue must be explainable in terms of these patterns.**

If it can't be explained that way, we do not build it like that. We extend the design principles instead—on purpose, in writing, with architectural review.

This document is your architectural compass. Use it to guide every design decision, and evolve it when new patterns emerge.
