# Test Matrix — Asset & Asset Library Invariants

**Status:** Active
**Test file:** `pkg/core/tests/contracts/test_asset_invariants.py`

---

## Section 1: Asset Entity Integrity

### INV-ASSET-APPROVED-IMPLIES-READY-001

| ID | Scenario | Expected | Test |
|----|----------|----------|------|
| TAAIR-001 | state=ready, approved=true | Valid | `TestInvAssetApprovedImpliesReady001::test_taair_001_ready_approved_valid` |
| TAAIR-002 | state=new, approved=true | Rejected: `INV-ASSET-APPROVED-IMPLIES-READY-001-VIOLATED` | `TestInvAssetApprovedImpliesReady001::test_taair_002_new_approved_rejected` |
| TAAIR-003 | state=enriching, approved=true | Rejected: `INV-ASSET-APPROVED-IMPLIES-READY-001-VIOLATED` | `TestInvAssetApprovedImpliesReady001::test_taair_003_enriching_approved_rejected` |
| TAAIR-004 | state=ready, approved=false | Valid (not yet approved) | `TestInvAssetApprovedImpliesReady001::test_taair_004_ready_not_approved_valid` |

### INV-ASSET-SOFTDELETE-SYNC-001

| ID | Scenario | Expected | Test |
|----|----------|----------|------|
| TSDS-001 | is_deleted=true + deleted_at set | Valid | `TestInvAssetSoftdeleteSync001::test_tsds_001_deleted_with_timestamp_valid` |
| TSDS-002 | is_deleted=false + deleted_at=null | Valid | `TestInvAssetSoftdeleteSync001::test_tsds_002_not_deleted_no_timestamp_valid` |
| TSDS-003 | is_deleted=true + deleted_at=null | Rejected: `INV-ASSET-SOFTDELETE-SYNC-001-VIOLATED` | `TestInvAssetSoftdeleteSync001::test_tsds_003_deleted_no_timestamp_rejected` |
| TSDS-004 | is_deleted=false + deleted_at set | Rejected: `INV-ASSET-SOFTDELETE-SYNC-001-VIOLATED` | `TestInvAssetSoftdeleteSync001::test_tsds_004_not_deleted_with_timestamp_rejected` |

### INV-ASSET-CANONICAL-KEY-FORMAT-001

| ID | Scenario | Expected | Test |
|----|----------|----------|------|
| TCKF-001 | Valid 64-char lowercase hex | Valid | `TestInvAssetCanonicalKeyFormat001::test_tckf_001_valid_sha256_hex` |
| TCKF-002 | 63-char string | Rejected: `INV-ASSET-CANONICAL-KEY-FORMAT-001-VIOLATED` | `TestInvAssetCanonicalKeyFormat001::test_tckf_002_too_short_rejected` |
| TCKF-003 | 65-char string | Rejected: `INV-ASSET-CANONICAL-KEY-FORMAT-001-VIOLATED` | `TestInvAssetCanonicalKeyFormat001::test_tckf_003_too_long_rejected` |
| TCKF-004 | 64-char non-hex | Rejected: `INV-ASSET-CANONICAL-KEY-FORMAT-001-VIOLATED` | `TestInvAssetCanonicalKeyFormat001::test_tckf_004_non_hex_rejected` |
| TCKF-005 | 64-char uppercase hex | Rejected: `INV-ASSET-CANONICAL-KEY-FORMAT-001-VIOLATED` | `TestInvAssetCanonicalKeyFormat001::test_tckf_005_uppercase_rejected` |

### INV-ASSET-STATE-MACHINE-001

| ID | Scenario | Expected | Test |
|----|----------|----------|------|
| TASM-001 | new -> enriching | Valid | `TestInvAssetStateMachine001::test_tasm_001_new_to_enriching` |
| TASM-002 | enriching -> ready | Valid | `TestInvAssetStateMachine001::test_tasm_002_enriching_to_ready` |
| TASM-003 | enriching -> new (revert) | Valid | `TestInvAssetStateMachine001::test_tasm_003_enriching_to_new_revert` |
| TASM-004 | any -> retired | Valid | `TestInvAssetStateMachine001::test_tasm_004_any_to_retired` |
| TASM-005 | new -> ready (skip enriching) | Rejected: `INV-ASSET-STATE-MACHINE-001-VIOLATED` | `TestInvAssetStateMachine001::test_tasm_005_new_to_ready_rejected` |
| TASM-006 | ready -> new | Rejected: `INV-ASSET-STATE-MACHINE-001-VIOLATED` | `TestInvAssetStateMachine001::test_tasm_006_ready_to_new_rejected` |
| TASM-007 | ready -> enriching | Rejected: `INV-ASSET-STATE-MACHINE-001-VIOLATED` | `TestInvAssetStateMachine001::test_tasm_007_ready_to_enriching_rejected` |
| TASM-008 | same state no-op | Valid | `TestInvAssetStateMachine001::test_tasm_008_same_state_noop` |
| TASM-009 | retired -> anything | Rejected: `INV-ASSET-STATE-MACHINE-001-VIOLATED` | `TestInvAssetStateMachine001::test_tasm_009_retired_to_anything_rejected` |

---

## Section 2: Enrichment Pipeline

### INV-ASSET-DURATION-REQUIRED-FOR-READY-001

| ID | Scenario | Expected | Test |
|----|----------|----------|------|
| TDRR-001 | duration_ms=1320000 | Promoted to ready | `TestInvAssetDurationRequiredForReady001::test_tdrr_001_valid_duration_promotes` |
| TDRR-002 | duration_ms=None | Stays in new | `TestInvAssetDurationRequiredForReady001::test_tdrr_002_none_duration_stays_new` |
| TDRR-003 | duration_ms=0 | Stays in new | `TestInvAssetDurationRequiredForReady001::test_tdrr_003_zero_duration_stays_new` |

### INV-ASSET-APPROVAL-OPERATOR-ONLY-001

| ID | Scenario | Expected | Test |
|----|----------|----------|------|
| TAOO-001 | After enrichment, approved=false | Valid | `TestInvAssetApprovalOperatorOnly001::test_taoo_001_enrichment_never_approves` |
| TAOO-002 | Enrichment sets approved=true | Violation detected by APPROVED-IMPLIES-READY | `TestInvAssetApprovalOperatorOnly001::test_taoo_002_enrichment_setting_approved_is_violation` |

### INV-ASSET-REPROBE-RESETS-APPROVAL-001

| ID | Scenario | Expected | Test |
|----|----------|----------|------|
| TRRA-001 | Reprobe clears all stale data | approved=false, technical fields=null | `TestInvAssetReprobeResetsApproval001::test_trra_001_reprobe_clears_all_stale_data` |
| TRRA-002 | Non-CHAPTER markers survive | AVAILABILITY preserved, CHAPTER deleted | `TestInvAssetReprobeResetsApproval001::test_trra_002_non_chapter_markers_survive` |
| TRRA-003 | CHAPTER markers removed | All CHAPTER markers deleted | `TestInvAssetReprobeResetsApproval001::test_trra_003_chapter_markers_removed` |

---

## Section 3: Metadata Integrity

### INV-ASSET-PROBE-ONLY-FIELD-AUTHORITY-001

| ID | Scenario | Expected | Test |
|----|----------|----------|------|
| TPFA-001 | Non-probe fields authoritative | Valid | `TestInvAssetProbeOnlyFieldAuthority001::test_tpfa_001_non_probe_authoritative_valid` |
| TPFA-002 | runtime_seconds authoritative | Rejected: probe-only fields cannot be authoritative | `TestInvAssetProbeOnlyFieldAuthority001::test_tpfa_002_runtime_seconds_authoritative_rejected` |
| TPFA-003 | video_codec authoritative | Rejected: probe-only fields cannot be authoritative | `TestInvAssetProbeOnlyFieldAuthority001::test_tpfa_003_video_codec_authoritative_rejected` |
| TPFA-004 | Probe fields present, not authoritative | Valid | `TestInvAssetProbeOnlyFieldAuthority001::test_tpfa_004_probe_fields_present_but_not_authoritative_valid` |

### INV-ASSET-DURATION-CONTRACTUAL-TRUTH-001

| ID | Scenario | Expected | Test |
|----|----------|----------|------|
| TDCT-001 | Duration set at enrichment, unchanged | Planning sees same value | `TestInvAssetDurationContractualTruth001::test_tdct_001_duration_set_at_enrichment` |
| TDCT-002 | Asset library returns stored value | No recalculation | `TestInvAssetDurationContractualTruth001::test_tdct_002_asset_library_returns_stored_value` |

### INV-ASSET-MARKER-BOUNDS-001

| ID | Scenario | Expected | Test |
|----|----------|----------|------|
| TAMB-001 | start=0, end=30000, duration=1320000 | Valid | `TestInvAssetMarkerBounds001::test_tamb_001_valid_marker_within_bounds` |
| TAMB-002 | start=0, end=duration (boundary) | Valid | `TestInvAssetMarkerBounds001::test_tamb_002_marker_at_boundaries` |
| TAMB-003 | end=2000000 > duration=1320000 | Rejected: `INV-ASSET-MARKER-BOUNDS-001-VIOLATED` | `TestInvAssetMarkerBounds001::test_tamb_003_end_exceeds_duration_rejected` |
| TAMB-004 | start=-1 | Rejected: `INV-ASSET-MARKER-BOUNDS-001-VIOLATED` | `TestInvAssetMarkerBounds001::test_tamb_004_negative_start_rejected` |

---

## Section 4: Schedulability & Library Boundary

### INV-ASSET-SCHEDULABLE-TRIPLE-GATE-001

| ID | Scenario | Expected | Test |
|----|----------|----------|------|
| TSTG-001 | ready + approved + not-deleted | Schedulable | `TestInvAssetSchedulableTripleGate001::test_tstg_001_all_three_conditions_schedulable` |
| TSTG-002 | ready + approved + deleted | Not schedulable | `TestInvAssetSchedulableTripleGate001::test_tstg_002_deleted_not_schedulable` |
| TSTG-003 | ready + not-approved + not-deleted | Not schedulable | `TestInvAssetSchedulableTripleGate001::test_tstg_003_not_approved_not_schedulable` |
| TSTG-004 | new + not-approved + not-deleted | Not schedulable | `TestInvAssetSchedulableTripleGate001::test_tstg_004_not_ready_not_schedulable` |
| TSTG-005 | enriching + not-approved + not-deleted | Not schedulable | `TestInvAssetSchedulableTripleGate001::test_tstg_005_enriching_not_schedulable` |
| TSTG-006 | All 8 permutations exhaustive | Exactly 1 schedulable | `TestInvAssetSchedulableTripleGate001::test_tstg_006_all_permutations` |

### INV-ASSET-LIBRARY-PLANNING-ONLY-001

| ID | Scenario | Expected | Test |
|----|----------|----------|------|
| TALP-001 | channel_manager.py imports | No Asset Library references | `TestInvAssetLibraryPlanningOnly001::test_talp_001_no_asset_library_in_channel_manager` |
| TALP-002 | playout_session.py imports | No Asset Library references | `TestInvAssetLibraryPlanningOnly001::test_talp_002_no_asset_library_in_playout_session` |
