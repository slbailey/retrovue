# Pipeline Migration Feature Flags

This document defines the **feature flags** used during migration from the current inline enrichment pipeline to the contract-driven architecture (discover → reconcile → enqueue → worker runtime). Without these flags, switching behavior between inline enrichment and the job queue risks **double processing**, **inconsistent metadata**, and **broken tests**.

**Reference:** `PIPELINE_MIGRATION_ARCHITECTURE.md`, `PIPELINE_MIGRATION_TASK_PLAN.md`, `docs/contracts/core/*.md`.

---

## Purpose

- **Safe rollout:** Migrate one step at a time without running both the old and new paths in a way that processes the same asset twice or writes conflicting metadata.
- **Testability:** Run tests and environments in a known state (e.g. “inline only”, “enqueue + inline”, “enqueue + worker only”).
- **Rollback:** Revert to a previous behavior by changing configuration, not code.

---

## Flag Definitions

Flags are boolean settings. They MAY be read from environment variables or from application settings (e.g. `server/src/retrovue/infra/settings.py`). Defaults are chosen so that **before** the corresponding phase is enabled, behavior matches the pre-migration pipeline.

| Flag | Default | When introduced | Meaning when `True` |
|------|---------|------------------|---------------------|
| **ENABLE_FINGERPRINT_UPDATES** | `false` | Phase 2 | Reconciliation “compare” uses fingerprint; outcome “update” is applied (refresh fingerprint and source-derived metadata; enqueue stub/real jobs). When `false`, treat “locator present in catalog” as no_action for fingerprint comparison (or skip fingerprint comparison). |
| **ENABLE_PROCESSOR_QUEUE** | `false` | Phase 3 | Reconciliation “enqueue” step calls the real job enqueue API; jobs are written to `processor_jobs`. When `false`, enqueue is no-op or stub (log only). |
| **ENABLE_RUNTIME_EXECUTION** | `false` | Phase 4 | Workers execute jobs via the **processor runtime** (context, validate, apply). When `true`, workers must use only the runtime; no direct enricher calls. When `false`, workers either do not run or use a legacy/minimal path (Phase 3 placeholder). |

**Optional (document only):** A single composite flag such as `PIPELINE_MIGRATION_MODE` with values `inline` | `enqueue_inline` | `enqueue_worker` is possible but not required; the three boolean flags above are sufficient and easier to reason about per phase.

---

## Migration States

During migration the system runs in one of three **states**. Flags determine which state is active. Only one enrichment path (inline vs worker) must run per asset to avoid double processing.

| State | ENABLE_FINGERPRINT_UPDATES | ENABLE_PROCESSOR_QUEUE | ENABLE_RUNTIME_EXECUTION | Behavior |
|-------|----------------------------|-------------------------|---------------------------|----------|
| **State 1** | `false` | `false` | `false` | **Discover → inline enrich.** Current behavior: discovery (Phase 1) drives ingest; reconciliation workflow may exist but “update when fingerprint differs” is off; no job enqueue; enrichment is inline in the create path. |
| **State 2** | `true` | `true` | `false` | **Discover → enqueue + inline enrich.** Reconciliation runs full workflow: compare with fingerprint, apply update/no_action/mark_unavailable, and **enqueue** jobs. Workers are off or not used for catalog updates. Inline enrichment still runs in the create path so new assets get metadata. No double processing: either enqueue is stub (no workers) or inline is disabled for create and only enqueue runs (then workers would need to run with a minimal runtime). See “State 2 semantics” below. |
| **State 3** | `true` | `true` | `true` | **Discover → enqueue → worker runtime.** Reconciliation enqueues jobs only; **no inline enrichment** in the ingest path. Workers drain the queue and run processors via the formal processor runtime. Single enrichment path = workers only. |

**State 2 semantics (avoid double processing):**

- **Option A (recommended):** In State 2, reconciliation **enqueues** real jobs, but **inline enrichment remains on** for the **create** path only (new assets get metadata immediately). Workers are **not** run. So: new asset → inline enricher pipeline; updated asset (fingerprint changed) → enqueue only (job sits in queue until State 3). No double processing because workers are off.
- **Option B:** In State 2, turn **off** inline enrichment for new assets and **run workers** with the minimal/placeholder runtime from Phase 3. Then enrichment is workers-only; enqueue is real. Ensure ENABLE_RUNTIME_EXECUTION is still `false` so the “formal” runtime is not required; workers use the Phase 3 minimal runtime.

The task plan and code MUST enforce: **never run both inline enrichment and worker execution for the same asset in the same ingest run.** Either inline runs (and workers are off or enqueue is stub), or workers run (and inline is off for that path). Flag combinations that would cause both to run for the same target are invalid and tests must assert the chosen policy.

---

## Where Flags Are Read

- **Settings module:** `server/src/retrovue/infra/settings.py` (or equivalent). Add three optional boolean fields with the defaults above and env aliases `ENABLE_FINGERPRINT_UPDATES`, `ENABLE_PROCESSOR_QUEUE`, `ENABLE_RUNTIME_EXECUTION`.
- **Reconciliation / ingest:** When determining whether to apply “update” (fingerprint differs), read `ENABLE_FINGERPRINT_UPDATES`. When calling the enqueue API, if `ENABLE_PROCESSOR_QUEUE` is `false`, call stub/no-op enqueue; if `true`, call real enqueue.
- **Create path (inline enrichment):** When `ENABLE_PROCESSOR_QUEUE` is `true` and `ENABLE_RUNTIME_EXECUTION` is `true`, the create path MUST NOT run the inline enricher pipeline (so that only workers do enrichment). When either is `false`, the create path MAY run inline enrichment (current behavior).
- **Worker:** When claiming and executing jobs, if `ENABLE_RUNTIME_EXECUTION` is `true`, use only the formal processor runtime (Phase 4). If `false`, workers may use the minimal runtime (Phase 3) or not run at all, depending on phase.

---

## Risks Without Flags

- **Double processing:** Both inline enricher and worker run for the same asset → duplicate work, possible race, or overwriting metadata.
- **Inconsistent metadata:** One path writes duration/codec, the other overwrites or merges in a different order → flaky tests or wrong catalog state.
- **Broken tests:** Tests that assume “inline only” or “worker only” fail when the other path is accidentally enabled. Explicit flags (and test fixtures that set them) keep test state deterministic.

---

## Test and CI Policy

- **Unit and contract tests:** Set flags explicitly in fixtures or env so that the test’s expected path is active (e.g. `ENABLE_PROCESSOR_QUEUE=false` for pre-Phase 3 tests).
- **Integration tests:** For “reconciliation → enqueue → worker” tests, set `ENABLE_PROCESSOR_QUEUE=true` and `ENABLE_RUNTIME_EXECUTION=true` and disable inline enrichment for the create path in that test.
- **CI:** Defaults can remain “State 1” until Phase 2/3/4 are merged; then CI can run a second matrix or job with State 2/3 flags on for migration tests.

---

## Summary

| Flag | Phase | Effect when `True` |
|------|-------|--------------------|
| ENABLE_FINGERPRINT_UPDATES | 2 | Reconciliation applies “update” when fingerprint differs; enqueue (stub or real) called for updated assets. |
| ENABLE_PROCESSOR_QUEUE | 3 | Real job enqueue; jobs stored in `processor_jobs`; workers can drain queue. |
| ENABLE_RUNTIME_EXECUTION | 4 | Workers use formal processor runtime only; no direct enricher calls. When true, inline enrichment in ingest must be off to avoid double processing. |

**Invariant:** At any time, at most one enrichment path runs per asset (inline XOR worker). Flags and code must preserve this.
