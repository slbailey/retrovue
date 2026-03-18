# Canonical Rule Ledger — Redirect Stub

> ⚠️ **This root-level file is a redirect stub.**
> The authoritative Canonical Rule Ledger has been migrated to:
> **[docs/contracts/CANONICAL_RULE_LEDGER.md](docs/contracts/CANONICAL_RULE_LEDGER.md)**

Please update any links pointing here. This file is preserved only as a breadcrumb.

---

## Why This File Exists

Prior to the 2025-07-14 governance canonicalization pass, this root-level file contained
the full ledger content. That content has now been moved to `docs/contracts/CANONICAL_RULE_LEDGER.md`,
which is the single authoritative location for all canonical rule definitions.

## Notable Status Changes (Summary)

The canonical ledger at `docs/contracts/CANONICAL_RULE_LEDGER.md` has been updated with the
following governance-pass status changes:

| Rule | Previous Status | New Status | Reason |
|------|----------------|------------|--------|
| LAW-003 | yes (active) | **RETIRED** | Superseded by Phase 8 BlockPlan model |
| LAW-002 | PARTIALLY-TESTED | **yes** | Rewritten under BlockPlan semantics; Law002HardStopContractTests enforce block fence |
| LAW-005 | CONFLICT-PENDING | **RETIRED** | Superseded by INV-SCHED-GRID-FILLER-PADDING (filler always starts at frame 0) |
| AIR-013 | CONFLICT-PENDING | **RESOLVED** | MasterClock governs CT/scheduling; OutputTiming governs delivery pacing independently |
