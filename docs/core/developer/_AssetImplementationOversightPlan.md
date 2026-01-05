# Asset Implementation Oversight Plan

A staged, reviewable plan to deliver the Asset domain and support well-tested Collection Ingest. Each milestone is concrete and makes review/validation easy.

---

## Milestone 1 — Asset Domain Skeleton

**Objective:**  
Establish a minimal Asset domain and persistence layer so Collection Ingest can operate on real Asset records _without violating invariants_.

**What to build:**

- **Asset model:**
  - Includes all contract-required fields: identity, lifecycle, tech metadata, ops flags, canonical key, enricher snapshot.
  - Unique constraint: (`collection_uuid`, `canonical_key`) (at DB level—makes duplicate writes impossible).
- **Minimal infrastructure:**
  - `AssetRepository` and `UnitOfWork`
    - Fetch by (`collection_uuid`, `canonical_key`)
    - Create asset
    - Update existing asset
    - Atomic commit/rollback

**Acceptance Criteria:**

- Can create and fetch Assets with all required fields.
- The unique constraint _provably_ rejects duplicates (can demonstrate a failing write).
- UoW ensures atomicity (forced error → no partial writes).
- No persistence logic in the importer—importers cannot persist.

**Review Checklist:**

- Table/index names & types match domain docs.
- `approved_for_broadcast` **never defaults to true**.
- UoW fully isolates a transaction per ingest run.

---

## Milestone 2 — Canonical Identity & Duplicate Handling

**Objective:**  
Support contract rules B-16, D-9 through D-12 (canonical asset identity, duplicate prevention, fast lookup).

**What to build:**

- Implement canonical identity per source type:
  - _Plex_: `external_id + collection_id`
  - _Filesystem_: normalized `file_path + collection_id`
- _Collection Ingest logic_:
  - For each discovered item:
    - Compute canonical key
    - Fetch by (`collection_uuid`, `canonical_key`)
      - _If not found_ → stage as **create**
      - _If found_ → stage as **update** or **skip** (see next milestone)
  - Do **not** throw operator errors for duplicates—handle normally as contract decisions.

**Acceptance Criteria:**

- Ingest of a repeated item in a collection never creates a second asset.
- Output stats reflect ingested / updated / skipped per contract.
- JSON output includes contract-mandated counters + `last_ingest_time`.

**Review Checklist:**

- Canonical key logic is deterministic & documented (including path normalization).
- Unique constraint only triggers in error—serves as a safety net.

---

## Milestone 3 — Change Detection (Content & Enricher)

**Objective:**  
Meet rules B-17, B-18, D-10 to D-12: Only update assets if the content OR enricher configuration changes.

**What to build:**

- **Content Change Detection:**
  - Use strong hash when available; else use fallback (e.g., size + mtime for FS).
- **Enricher Config Checksum:**
  - Stable hash of `{enricher_id, priority}`—must be order-independent.
- **Decision Matrix:**
  - _No content change_ **and** _No enricher change_ → **skip**
  - _Content or enricher change_ → **update**
    - Refresh metadata, reset checksums
    - Reset lifecycle (`new` or `enriching` if previously `ready`)
    - Clear `approved_for_broadcast`

**Acceptance Criteria:**

- Content change → “updated” stat is incremented, not “ingested.”
- Enricher change alone → also increments “updated.”
- No changes → “skipped.”
- Assets that were `ready` do **not** remain so after update.

**Review Checklist:**

- Enricher checksum is deterministic (pre-hash sort).
- No path leaves an “updated” asset in `ready` state.

---

## Milestone 4 — Lifecycle Management

**Objective:**  
Protect scheduling safety by enforcing state transitions in ingest.

**What to build:**

- All new assets must start at `new` or `enriching`.
- Any updated “ready” asset is reset:
  - State set to `enriching` (or `new`)
  - `approved_for_broadcast = false`

**Acceptance Criteria:**

- No asset is ever created in `ready`.
- Updated assets are **never** eligible for scheduling until re-enriched.

**Review Checklist:**

- Search for any branch that creates assets in `ready`—there should be none.

---

## Milestone 5 — Real Importer Integration (First Path: Filesystem)

**Objective:**  
Replace all mocks with a real importer; show end-to-end flow on filesystem.

**What to build:**

- Filesystem importer that:
  - Validates ingestible (path exists, mapped)
  - Enumerates under scope (collection/title/season/episode filters)
  - Returns normalized asset items _with best-effort content signature_
  - Computes canonical key as normalized path + `collection_id`

**Acceptance Criteria:**

- Running collection ingest on a test folder produces plausible discovered/ingested numbers.
- Dry-run prints planned actions; `--test-db` isolates all writes (contract).

**Review Checklist:**

- Importer does **not** perform persistence.
- Scope narrowing truly limits enumeration as expected.

---

## Milestone 6 — Transactionality & Output Contract

**Objective:**  
CLI behavior, stats, output format, and atomicity match contract 1:1.

**What to build:**

- Wire CLI to real Collection Ingest service:
  - Exact contract exit codes & messages
  - Dry-run always disables DB writes (overrides test-db)
  - JSON output: status, scope, asset IDs, stats, `last_ingest_time`

**Acceptance Criteria:**

- All CLI contract tests pass on exit code + JSON output shape.
- `last_ingest_time` is updated _once per run_ on success (even if everything is skipped).

**Review Checklist:**

- No DB writes on dry-run (proved via logs/guard).
- Test that `last_ingest_time` is atomically updated—not incremented item-by-item.

---

## Milestone 7 — Observability & Guardrails

**Objective:**  
Enable diagnosis and support without code access.

**What to build:**

- Add structured logs for:
  - Validation gates hit/failed
  - Per-item decisions: create/update/skip (with reason)
  - Transaction start/commit/rollback
- Add ingest counters to service return that match CLI/JSON stats.

**Acceptance Criteria:**

- A log trace for any ingest run allows you to see _why_ each asset was created/updated/skipped.
- Rollback events are visible and explain the error.

**Review Checklist:**

- Log volume is bounded (summary or throttled for big collections).
- Never log sensitive data (paths OK; **no** tokens/secrets).

---

## ⚠️ Risk Register (Keep Front-of-Mind)

- **Canonical key drift:** If importer logic changes, keys change! Treat as content change, or design a migration path.
- **Hash cost:** SHA-256 is expensive on big files; support staged shortcuts (mtime/size fast path, full hash on-demand).
- **State leaks:** Ingest must _never_ leave an updated asset in `ready` (test this path aggressively).

---

## ✅ Definition of Done — This Phase

- **All** Collection Ingest contract tests pass using real persistence and a real importer.
- Running against a small real dataset produces sane ingest stats and correct asset lifecycle behavior.
- Every ingest result is fully explained by logs + JSON output — you never need a debugger.
- **It is impossible**—by code path or accident—to create an asset in `ready` or update an asset and leave it `ready`.

---
