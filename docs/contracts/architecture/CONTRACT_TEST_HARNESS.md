# Contract Test Harness — Catalog & Processor Contracts

This document specifies how **contract tests** enforce the catalog and processor contracts in `docs/contracts/core/`. Without this harness, the contracts remain documentation only; the tests are the executable specification that implementations must satisfy.

**Reference:** `docs/contracts/core/*.md`, `PIPELINE_MIGRATION_TASK_PLAN.md`, `server/tests/contracts/README.md`.

---

## Purpose

- **Traceability:** Every rule or guarantee in a contract has at least one test that verifies it. Tests reference the contract document and (where applicable) the section or rule ID.
- **Enforcement:** Implementations are validated against the contracts by running the test suite. A failing test indicates a contract violation or an implementation drift.
- **Migration guardrails:** During pipeline migration, new code must pass the contract tests for the layers it touches. Phases in the task plan require these tests to exist and pass before phase completion.

---

## Location and Naming

- **Directory:** `server/tests/contracts/`
- **Naming:** One test module per contract (or per contract domain). Use the pattern:
  - `test_container_discovery_contract.py` → ContainerDiscoveryContract
  - `test_catalog_reconciliation_contract.py` → CatalogReconciliationContract
  - `test_asset_media_identity_contract.py` → AssetMediaIdentityContract (may overlap with existing `test_asset_invariants.py`; either extend that file with contract reference or add this file and delegate to shared helpers)
  - `test_processor_job_queue_contract.py` → ProcessorJobQueueContract
  - `test_processor_execution_contract.py` → ProcessorExecutionContract
  - `test_processor_metadata_contract.py` → ProcessorMetadataContract

- **Contract reference:** Each test module MUST have a module-level docstring that states the contract document path, for example:
  ```text
  Contract tests for ContainerDiscoveryContract.
  Contract: docs/contracts/core/ContainerDiscoveryContract_v0.1.md
  ```
- **Test docstrings:** Individual test methods SHOULD reference the contract section or rule they verify (e.g. "Discovery Process step 1: discover locators", "Job Deduplication: no duplicate job for same identity").

---

## Conventions

1. **Deterministic:** No `time.sleep()` or wall-clock dependence. Use test doubles, frozen time, or in-memory state so that tests are repeatable and fast.
2. **No direct DB destruction:** Contract tests assume an isolated test database or transactional rollback; they MUST NOT truncate or drop tables in a way that breaks other tests or the test environment.
3. **Contract scope only:** Tests verify behavior described in the contract. They do not test implementation details that are not part of the contract (e.g. specific class names or private methods), unless needed to assert an observable guarantee.
4. **CI:** These tests are part of the normal contract test run (e.g. `pytest server/tests/contracts/ -m contract` or the project’s existing contract test invocation).

---

## Required Test Suites and Test Cases

Each contract has a corresponding test file and a minimum set of test cases. Implementations must cause these tests to pass when the corresponding phase is complete. New tests may be added as the contracts evolve; the list below is the minimum required set.

---

### 1. test_container_discovery_contract.py

**Contract:** `docs/contracts/core/ContainerDiscoveryContract_v0.1.md`

**Required test cases:**

| Test name | What it verifies |
|-----------|-------------------|
| `test_discovery_occurs_through_containers` | Media discovery is performed per container (collection); no discovery path that bypasses a container. |
| `test_source_may_have_multiple_containers` | A source can have multiple collections/containers; discovery is invoked per container. |
| `test_discovery_returns_locators_without_catalog_writes` | The discovery step returns locator-like data (e.g. list of DiscoveredLocator) and does not write to the catalog (no Asset/Media insert or update in discovery). |
| `test_locator_deterministic_for_same_item` | For the same importer item (same path_uri/provider_key), the derived locator string is identical across calls. |

**Optional (when applicable):** `test_discovery_scope_passed_to_importer` — when scope (title/season/episode) is provided and the importer supports it, discovery passes scope to the importer.

---

### 2. test_catalog_reconciliation_contract.py

**Contract:** `docs/contracts/core/CatalogReconciliationContract_v0.1.md`

**Required test cases:**

| Test name | What it verifies |
|-----------|-------------------|
| `test_reconciliation_idempotency` | Running reconciliation twice with the same source state (same discovered locators) produces no additional catalog changes (no duplicate creates, no redundant updates). |
| `test_reconciliation_outcome_create_when_absent` | When a locator is present in discovery and absent from the catalog, the outcome is create and a new asset (and optionally media) is created. |
| `test_reconciliation_outcome_no_action_when_unchanged` | When a locator is present in discovery and present in the catalog with the same fingerprint, the outcome is no_action and no mutation. |
| `test_reconciliation_outcome_update_when_fingerprint_differs` | When a locator is present in discovery and present in the catalog but the fingerprint differs, the outcome is update and the existing record is updated (fingerprint and source-derived metadata); a new record is NOT created. |
| `test_reconciliation_outcome_mark_unavailable_when_absent_from_source` | When a locator was previously in the catalog but is absent from the current discovery, the outcome is mark_unavailable and the record is marked unavailable (or soft-deleted); the row is NOT deleted. |
| `test_reconciliation_workflow_steps_in_order` | The reconciliation workflow executes in the contract order: discover → detect sidecars → compare → determine outcome → apply → enqueue jobs (enqueue may be stub). |
| `test_locator_uniqueness` | The tuple (source_id, container_id, locator) is unique in the catalog; duplicate locators within a container are not permitted (enforced by uniqueness or by deduplication in apply). |

---

### 3. test_asset_media_identity_contract.py

**Contract:** `docs/contracts/core/AssetMediaIdentityContract_v0.1.md`

**Required test cases:**

| Test name | What it verifies |
|-----------|-------------------|
| `test_scheduler_references_assets_not_media` | Schedule or playlist artifacts reference Asset (or logical program) identifiers, not raw media/file identifiers as the scheduling unit. (May be satisfied by existing INV-ASSET-MEDIA-IDENTITY tests.) |
| `test_media_identity_tuple_unique` | Where Media (or Asset-as-media) identity is stored, (source_id, container_id, locator) is unique; no duplicate locator within a container. |
| `test_same_locator_fingerprint_change_updates_no_new_entry` | When the same locator is seen again with a different fingerprint, the system updates the existing Media/Asset record and does not create a new one. |
| `test_locator_disappears_mark_unavailable_not_delete` | When a locator disappears from the source, the record is marked unavailable (or soft-deleted); the row is not hard-deleted. |

**Note:** Some of these may already be covered by `test_asset_invariants.py` (e.g. INV-ASSET-MEDIA-IDENTITY). This file can re-export or call those tests and add any remaining cases that are specific to the AssetMediaIdentityContract wording.

---

### 4. test_processor_job_queue_contract.py

**Contract:** `docs/contracts/core/ProcessorJobQueueContract_v0.1.md`

**Required test cases:**

| Test name | What it verifies |
|-----------|-------------------|
| `test_job_identity_unique` | A job is uniquely identified by (target_type, target_id). Two enqueue requests for the same target do not create two pending/running jobs (deduplication). |
| `test_job_queue_deduplication` | If a job already exists for a target (pending or running), enqueue does not create a duplicate; it may update priority only. |
| `test_job_lifecycle_pending_to_running_to_completed` | A job can transition pending → running → completed (runtime runs all applicable processors for the target). |
| `test_job_lifecycle_pending_to_running_to_failed` | A job can transition pending → running → failed (e.g. a processor in the sequence fails). |
| `test_job_retry_resets_to_pending_preserves_identity` | Retrying a failed job sets status to pending and preserves (target_type, target_id); no second job is created for the same target. |
| `test_job_priority_ordering` | When multiple jobs exist, higher-priority jobs are claimed before lower-priority jobs (worker or claim_next returns higher priority first). |
| `test_worker_claims_one_job_at_a_time` | Only one worker can claim a given job (status running); a second claim for the same job returns a different job or none. |
| `test_observable_state_queued_running_completed_failed` | The queue exposes or logs observable state for queued, running, completed, and failed jobs (e.g. counts or queryable status). |

---

### 5. test_processor_execution_contract.py

**Contract:** `docs/contracts/core/ProcessorExecutionContract_v0.1.md`

**Required test cases:**

| Test name | What it verifies |
|-----------|-------------------|
| `test_processor_receives_execution_context` | When a worker runs a job, the processor (or the runtime) receives execution context (e.g. processor_id, target_type, target_id, job_id, timestamp) and a read-only view of the shared ProcessingContext; processors treat both as read-only. |
| `test_processor_failure_does_not_modify_metadata` | When a processor raises an exception or fails, the catalog is not updated for that job; the asset/media state is unchanged. |
| `test_processor_result_validated_before_apply` | Processor results are validated (e.g. against produced_metadata or allowlist) before being merged into the context; invalid result causes job to fail and no apply. |
| `test_shared_context_single_transaction_persist` | Runtime loads target and related metadata once, merges all processor results into the shared ProcessingContext (no DB write per processor), and persists all changes in a single database transaction only after all processors succeed. |
| `test_processor_runs_recorded_per_execution` | After a successful job, processor_runs has one row per processor that ran (job_id, processor_id, target_type, target_id, status, started_at, completed_at); after a failed job, run rows exist for each processor that was invoked before the failure. Supports execution history, staleness detection, and auditability. |
| `test_execution_isolated_from_scheduler` | Processor execution is not triggered by the scheduler or horizon expansion; only workers (or explicit enqueue) trigger execution. |
| `test_observable_events_started_completed_failed_duration` | Execution produces observable events or logs: processor started, processor completed or failed, and duration. |

---

### 6. test_processor_metadata_contract.py

**Contract:** `docs/contracts/core/ProcessorMetadataContract_v0.1.md`

**Required test cases:**

| Test name | What it verifies |
|-----------|-------------------|
| `test_processor_does_not_overwrite_operator_owned_field` | When an operator-owned field (e.g. approved_for_broadcast) is set to true, running a processor job for that asset does not set it to false or overwrite it. |
| `test_structured_metadata_in_structured_tables` | Metadata required by core logic (e.g. duration_ms, video_codec) is stored in structured tables/columns, not only in JSON. |
| `test_flexible_output_in_processor_outputs` | When a processor returns flexible or processor-specific output, it is stored in the processor_outputs table (processor_id, target_type, target_id, payload_json, created_at). |
| `test_processor_may_update_own_fields_when_media_changes` | Processors may update fields they own when the media (or fingerprint) changes; the apply path allows this for processor-owned fields. |

---

## Skeleton Test Files

Each of the six test files MUST exist and MUST contain:

1. A module docstring with the contract path (see above).
2. A test class (e.g. `TestContainerDiscoveryContract`) that groups the tests for that contract.
3. Stub test methods for each required test case in the table above; the body may be `pytest.skip("Phase N not yet implemented")` or a minimal assert (e.g. `assert True`) until the implementation is in place. Once the phase that implements the behavior is done, the skip is removed and the test is implemented to verify the contract.

**Example skeleton:**

```python
"""
Contract tests for CatalogReconciliationContract.
Contract: docs/contracts/core/CatalogReconciliationContract_v0.1.md
"""

import pytest


class TestCatalogReconciliationContract:
    """Verify CatalogReconciliationContract guarantees."""

    def test_reconciliation_idempotency(self):
        """Reconciliation with same source state produces no additional catalog changes."""
        pytest.skip("Phase 2 not yet implemented")

    def test_reconciliation_outcome_create_when_absent(self):
        """Present in source, absent in catalog → create."""
        pytest.skip("Phase 2 not yet implemented")

    # ... remaining required tests
```

---

## Phase–Test Mapping

| Phase | Contract(s) | Test file(s) |
|-------|-------------|---------------|
| 1 | ContainerDiscoveryContract | test_container_discovery_contract.py |
| 2 | CatalogReconciliationContract, AssetMediaIdentityContract (partial) | test_catalog_reconciliation_contract.py, test_asset_media_identity_contract.py (or extend test_asset_invariants) |
| 3 | ProcessorJobQueueContract | test_processor_job_queue_contract.py |
| 4 | ProcessorExecutionContract | test_processor_execution_contract.py |
| 5 | ProcessorMetadataContract | test_processor_metadata_contract.py |

When a phase is completed, the corresponding contract tests MUST pass (skips removed, behavior implemented and asserted). The task plan validation steps require running these tests.

---

## Running Contract Tests

- **Full contract suite:** `pytest server/tests/contracts/ -v` (or with project’s contract marker).
- **Per-contract:**  
  `pytest server/tests/contracts/test_container_discovery_contract.py -v`  
  `pytest server/tests/contracts/test_catalog_reconciliation_contract.py -v`  
  … etc.

CI MUST run the contract tests as part of the pipeline so that contract violations are caught before merge or release.
