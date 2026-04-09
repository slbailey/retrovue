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

### INV-ASSET-REENRICH-RESETS-STALE-001

| ID | Scenario | Expected | Test |
|----|----------|----------|------|
| TERS-001 | Stale asset metadata cleared | duration_ms, video_codec, audio_codec, container = null | `TestInvAssetReenrichResetsStale001::test_ters_001_stale_asset_metadata_cleared` |
| TERS-002 | Stale asset approval reset | approved_for_broadcast = false | `TestInvAssetReenrichResetsStale001::test_ters_002_stale_asset_approval_reset` |
| TERS-003 | CHAPTER markers cleared, non-CHAPTER preserved | AVAIL survives, CHAPTER deleted | `TestInvAssetReenrichResetsStale001::test_ters_003_chapter_markers_cleared_non_chapter_preserved` |
| TERS-004 | State transitions through enriching | new → enriching → ready/new legal | `TestInvAssetReenrichResetsStale001::test_ters_004_state_transitions_through_enriching` |
| TERS-005 | Never approves after re-enrichment | approved_for_broadcast = false after full lifecycle | `TestInvAssetReenrichResetsStale001::test_ters_005_never_approves_after_reenrichment` |

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

---

## Section 5: Validation & Enrichment Pipeline

**Test files:**
- `pkg/core/tests/contracts/ingest/test_inv_validator_output_shape.py`
- `pkg/core/tests/contracts/ingest/test_inv_enricher_idempotent.py`
- `pkg/core/tests/contracts/ingest/test_inv_catalog_ready_schedulable.py`
- `pkg/core/tests/contracts/ingest/test_inv_enricher_execution_mode.py`

### INV-VALIDATOR-OUTPUT-SHAPE-001

| ID | Scenario | Expected | Test |
|----|----------|----------|------|
| TVOS-001 | All required fields populated | Accepted | `TestInvValidatorOutputShape001::test_valid_result_accepted` |
| TVOS-002 | Missing status field | Rejected: `INV-VALIDATOR-OUTPUT-SHAPE-001-VIOLATED` | `TestInvValidatorOutputShape001::test_missing_status_raises` |
| TVOS-003 | Invalid status value ("partial") | Rejected: `INV-VALIDATOR-OUTPUT-SHAPE-001-VIOLATED` | `TestInvValidatorOutputShape001::test_invalid_status_raises` |
| TVOS-004 | Error entry missing code field | Rejected: `INV-VALIDATOR-OUTPUT-SHAPE-001-VIOLATED` | `TestInvValidatorOutputShape001::test_error_missing_code_raises` |
| TVOS-005 | Error entry missing validator field | Rejected: `INV-VALIDATOR-OUTPUT-SHAPE-001-VIOLATED` | `TestInvValidatorOutputShape001::test_error_missing_validator_raises` |
| TVOS-006 | Extra fields on valid result | Accepted (additive-only) | `TestInvValidatorOutputShape001::test_shape_is_additive_only` |
| TVOS-007 | Error entry missing message field | Rejected: `INV-VALIDATOR-OUTPUT-SHAPE-001-VIOLATED` | `TestInvValidatorOutputShape001::test_error_missing_message_raises` |
| TVOS-008 | Warning entry missing code field | Rejected: `INV-VALIDATOR-OUTPUT-SHAPE-001-VIOLATED` | `TestInvValidatorOutputShape001::test_warning_missing_code_raises` |
| TVOS-009 | Warning entry missing validator field | Rejected: `INV-VALIDATOR-OUTPUT-SHAPE-001-VIOLATED` | `TestInvValidatorOutputShape001::test_warning_missing_validator_raises` |
| TVOS-010 | Failed result with proper error entries | Accepted | `TestInvValidatorOutputShape001::test_failed_result_accepted` |
| TVOS-011 | Per-validator status invalid value | Rejected: `INV-VALIDATOR-OUTPUT-SHAPE-001-VIOLATED` | `TestInvValidatorOutputShape001::test_per_validator_status_invalid` |
| TVOS-012 | Per-validator status pass | Accepted | `TestInvValidatorOutputShape001::test_per_validator_status_pass` |
| TVOS-013 | Per-validator status fail | Accepted | `TestInvValidatorOutputShape001::test_per_validator_status_fail` |
| TVOS-014 | Per-validator status warn | Accepted | `TestInvValidatorOutputShape001::test_per_validator_status_warn` |

### INV-ENRICHER-IDEMPOTENT-001

| ID | Scenario | Expected | Test |
|----|----------|----------|------|
| TEID-001 | Run enricher twice, same input | Identical results (excluding timestamps) | `TestInvEnricherIdempotent001::test_same_input_same_output` |
| TEID-002 | Re-running produces no duplicate side effects | Same fields on second run | `TestInvEnricherIdempotent001::test_no_duplicate_side_effects` |
| TEID-003 | Enricher result contains version field | version field present and non-empty | `TestInvEnricherIdempotent001::test_result_contains_version` |
| TEID-004 | Partial failure then retry | No duplicate side effects, clean result | `TestInvEnricherIdempotent001::test_partial_failure_recovery_no_duplicate_side_effects` |
| TEID-005 | Missing version field on result | Rejected: `INV-ENRICHER-IDEMPOTENT-001-VIOLATED` | `TestInvEnricherIdempotent001::test_missing_version_raises` |

### INV-CATALOG-READY-SCHEDULABLE-001

| ID | Scenario | Expected | Test |
|----|----------|----------|------|
| TCRS-001 | Ready asset accepted by scheduling | No probe or validation invoked | `TestInvCatalogReadySchedulable001::test_ready_asset_accepted_without_probe` |
| TCRS-002 | Unplayable asset not promoted to ready | Stays in new, approved=false | `TestInvCatalogReadySchedulable001::test_unplayable_asset_not_promoted` |
| TCRS-003 | Schedule compilation on ready assets | No validator or file-access check | `TestInvCatalogReadySchedulable001::test_scheduling_does_not_invoke_validators` |
| TCRS-004 | Enriching asset promoted to ready on approval | enriching → ready | `TestInvCatalogReadySchedulable001::test_enriching_asset_promoted_to_ready` |
| TCRS-005 | Enriching asset fails validation, stays enriching | No state change | `TestInvCatalogReadySchedulable001::test_enriching_asset_not_promoted_on_failure` |
| TCRS-006 | Ready asset becomes unplayable, exits ready | ready → retired, approved=false | `TestInvCatalogReadySchedulable001::test_asset_loses_playability_exits_ready` |

### INV-ENRICHER-EXECUTION-MODE-001

| ID | Scenario | Expected | Test |
|----|----------|----------|------|
| TEEM-001 | Immediate enricher declares mode | mode == IMMEDIATE | `TestInvEnricherExecutionMode001::test_immediate_enricher_declares_mode` |
| TEEM-002 | Background enricher declares mode | mode == BACKGROUND | `TestInvEnricherExecutionMode001::test_background_enricher_declares_mode` |
| TEEM-003 | Lazy enricher declares mode | mode == LAZY_ON_ACCESS | `TestInvEnricherExecutionMode001::test_lazy_enricher_declares_mode` |
| TEEM-004 | Every concrete enricher has execution mode | isinstance(mode, ExecutionMode) | `TestInvEnricherExecutionMode001::test_no_enricher_lacks_execution_mode` |
| TEEM-005 | Undeclared mode value ("on_demand") | Rejected | `TestInvEnricherExecutionMode001::test_undeclared_mode_rejected` |
| TEEM-006 | Only three declared modes exist | {immediate, lazy_on_access, background} | `TestInvEnricherExecutionMode001::test_execution_mode_enum_exhaustive` |
| TEEM-007 | System dispatches enricher by mode, not self-trigger | Dispatch log matches declared modes | `TestInvEnricherExecutionMode001::test_system_triggers_enricher_not_self_trigger` |
| TEEM-008 | Enricher does not self-invoke on construction | No enrich() call during __init__ | `TestInvEnricherExecutionMode001::test_enricher_does_not_self_invoke` |

---

## Section 5b: Enricher Observability (Phase 3)

**Test files:**
- `pkg/core/tests/contracts/ingest/test_inv_enricher_observability.py`
- `pkg/core/tests/contracts/ingest/test_inv_enricher_result_versioned.py`

### INV-ENRICHER-OBSERVABILITY-001

| ID | Scenario | Expected | Test |
|----|----------|----------|------|
| TEOB-001 | Pipeline with 3 enrichers produces 3 records | One enricher-run per enricher per asset | `TestInvEnricherObservability001::test_one_record_per_enricher_per_asset` |
| TEOB-002 | Each record contains required fields | enricher_name, asset_id, status, version, started_at, completed_at present | `TestInvEnricherObservability001::test_required_fields_present` |
| TEOB-003 | Failed enricher produces failed record | status=failed with error context | `TestInvEnricherObservability001::test_failed_enricher_produces_failed_record` |
| TEOB-004 | Records queryable by asset_id independently | FFprobe status retrievable without loading full ProcessorJob | `TestInvEnricherObservability001::test_records_queryable_per_asset` |
| TEOB-005 | Records queryable by enricher_name | All assets processed by a given enricher retrievable | `TestInvEnricherObservability001::test_records_queryable_per_enricher` |

### INV-ENRICHER-RESULT-VERSIONED-001

| ID | Scenario | Expected | Test |
|----|----------|----------|------|
| TERV-001 | Enricher v1 result persisted with version | Record contains version=v1 | `TestInvEnricherResultVersioned001::test_result_persisted_with_version` |
| TERV-002 | Same version re-run is idempotent | No new record, same result | `TestInvEnricherResultVersioned001::test_same_version_rerun_idempotent` |
| TERV-003 | Upgrade does not force bulk reprocessing | Existing v1 records unchanged after enricher upgrade to v2 | `TestInvEnricherResultVersioned001::test_upgrade_no_bulk_reprocessing` |
| TERV-004 | Stale results queryable by version comparison | Assets with enricher version < current detectable | `TestInvEnricherResultVersioned001::test_stale_results_queryable_by_version` |
| TERV-005 | Re-run at new version updates record | Record updated to version=v2 after re-enrichment | `TestInvEnricherResultVersioned001::test_rerun_at_new_version_updates_record` |

---

## Section 6: Source & Path Mapping (Phase 2)

**Test files:**
- `pkg/core/tests/contracts/ingest/test_inv_path_mapping_source_scoped.py`
- `pkg/core/tests/contracts/ingest/test_inv_path_validation_on_import.py`
- `pkg/core/tests/contracts/ingest/test_inv_source_type_registry.py`
- `pkg/core/tests/contracts/ingest/test_inv_validator_result_persistence.py`

### INV-PATH-MAPPING-SOURCE-SCOPED-001

| ID | Scenario | Expected | Test |
|----|----------|----------|------|
| TPMS-001 | Container inherits source mapping | Source mapping applied during resolution | `TestInvPathMappingSourceScoped001::test_container_inherits_source_mapping` |
| TPMS-002 | Container override takes precedence | Override prefix wins over source mapping | `TestInvPathMappingSourceScoped001::test_container_override_takes_precedence_for_its_prefix` |
| TPMS-003 | Source mapping with no container override | Source mapping is default | `TestInvPathMappingSourceScoped001::test_container_no_overrides_uses_source_mapping` |
| TPMS-004 | Provider-specific field names rejected | Rejected: `INV-PATH-MAPPING-SOURCE-SCOPED-001-VIOLATED` | `TestInvPathMappingSourceScoped001::test_provider_specific_field_names_rejected` |
| TPMS-005 | Canonical field names accepted | Accepted | `TestInvPathMappingSourceScoped001::test_canonical_field_names_accepted` |

### INV-PATH-VALIDATION-ON-IMPORT-001

| ID | Scenario | Expected | Test |
|----|----------|----------|------|
| TPVI-001 | Container import with no mappings fails | Import fails with diagnostic | `TestInvPathValidationOnImport001::test_no_path_mappings_import_fails_with_diagnostic` |
| TPVI-002 | Container import with valid mapping | Import succeeds | `TestInvPathValidationOnImport001::test_valid_mapping_import_succeeds` |
| TPVI-003 | Mapping not covering paths fails import | Import fails | `TestInvPathValidationOnImport001::test_mapping_not_covering_paths_import_fails` |
| TPVI-004 | Partial resolution proceeds with warning | Import proceeds with warning | `TestInvPathValidationOnImport001::test_partial_resolution_proceeds_with_warning` |
| TPVI-005 | Source add does not validate paths | Stored without validation | `TestInvPathValidationOnImport001::test_source_add_does_not_validate_paths` |

### INV-SOURCE-TYPE-REGISTRY-001

| ID | Scenario | Expected | Test |
|----|----------|----------|------|
| TSTR-001 | Known type resolves to importer | Correct importer class returned | `TestInvSourceTypeRegistry001::test_known_type_resolves_to_importer` |
| TSTR-002 | Unknown type rejected | Rejected: `INV-SOURCE-TYPE-REGISTRY-001-VIOLATED` | `TestInvSourceTypeRegistry001::test_unknown_type_rejected_with_invariant_tag` |
| TSTR-003 | No duplicate type keys in registry | Each type maps to exactly one importer | `TestInvSourceTypeRegistry001::test_no_duplicate_type_keys` |
| TSTR-004 | Rejected type log event contains registered types | Registered types listed | `TestInvSourceTypeRegistry001::test_rejected_type_log_event_contains_registered_types` |
| TSTR-005 | Resolve returns class not instance | Class object, not instantiated | `TestInvSourceTypeRegistry001::test_resolve_returns_class_not_instance` |

### INV-VALIDATOR-RESULT-PERSISTENCE-001

| ID | Scenario | Expected | Test |
|----|----------|----------|------|
| TVRP-001 | Valid result persisted after validation | Record exists with correct asset id and shape | `TestInvValidatorResultPersistence001::test_passing_result_persisted_with_correct_fields` |
| TVRP-002 | Failed result persisted with errors | Errors and per-validator statuses intact | `TestInvValidatorResultPersistence001::test_failing_result_persisted_with_errors_and_statuses` |
| TVRP-003 | Persisted result round-trips to canonical shape | No field loss or type coercion | `TestInvValidatorResultPersistence001::test_round_trip_preserves_canonical_shape` |
| TVRP-004 | State transition without persisted record | Rejected | `TestInvValidatorResultPersistence001::test_state_transition_without_persisted_record_rejected` |
| TVRP-005 | Warnings preserved in persisted result | Warning list not compressed or dropped | `TestInvValidatorResultPersistence001::test_persisted_results_include_warnings` |

## Section 7: Tag Canonical Form (Phase 6A)

**Test files:**
- `pkg/core/tests/contracts/test_inv_tag_canonical_form.py`
- `pkg/core/tests/contracts/test_inv_tag_migration_idempotent.py`

### INV-TAG-CANONICAL-FORM-001

| ID | Scenario | Expected | Test |
|----|----------|----------|------|
| TTCF-001 | Plain tag `hbo` canonicalized | `tag.hbo` | `TestInvTagCanonicalForm001::test_ttcf_001_plain_tag_canonicalized` |
| TTCF-002 | Colon-prefixed `TAG:hbo` canonicalized | `tag.hbo` | `TestInvTagCanonicalForm001::test_ttcf_002_colon_prefix_tag_canonicalized` |
| TTCF-003 | Network prefix `NETWORK:cbs` canonicalized | `network.cbs` | `TestInvTagCanonicalForm001::test_ttcf_003_network_prefix_canonicalized` |
| TTCF-004 | Already-canonical `tag.hbo` unchanged | `tag.hbo` | `TestInvTagCanonicalForm001::test_ttcf_004_already_canonical_unchanged` |
| TTCF-005 | Unknown namespace rejected | Rejected: `INV-TAG-CANONICAL-FORM-001-VIOLATED` | `TestInvTagCanonicalForm001::test_ttcf_005_unknown_namespace_rejected` |
| TTCF-006 | Empty value rejected | Rejected: `INV-TAG-CANONICAL-FORM-001-VIOLATED` | `TestInvTagCanonicalForm001::test_ttcf_006_empty_value_rejected` |
| TTCF-007 | Whitespace normalized in value | `tag.hbo max` -> `tag.hbo max` | `TestInvTagCanonicalForm001::test_ttcf_007_whitespace_normalized` |

### INV-TAG-MIGRATION-IDEMPOTENT-001

| ID | Scenario | Expected | Test |
|----|----------|----------|------|
| TTMI-001 | Double-canonicalize plain tag | Same result both times | `TestInvTagMigrationIdempotent001::test_ttmi_001_plain_tag_idempotent` |
| TTMI-002 | Double-canonicalize colon-prefixed tag | Same result both times | `TestInvTagMigrationIdempotent001::test_ttmi_002_colon_prefix_idempotent` |
| TTMI-003 | Double-canonicalize canonical tag | Same result both times | `TestInvTagMigrationIdempotent001::test_ttmi_003_canonical_idempotent` |
| TTMI-004 | Duplicate inputs collapse | `TAG:hbo` and `hbo` both produce `tag.hbo` | `TestInvTagMigrationIdempotent001::test_ttmi_004_duplicates_collapse` |
| TTMI-005 | All namespace prefixes idempotent | Each prefix round-trips correctly | `TestInvTagMigrationIdempotent001::test_ttmi_005_all_namespaces_idempotent` |

---

## Section 8: Source Watch Mode

### INV-WATCH-DELEGATES-001

| ID | Scenario | Expected | Test |
|----|----------|----------|------|
| TWD-001 | `source.py` CLI module does not import `watchdog` | Valid | `TestInvWatchDelegates001::test_twd_001_no_watchdog_import` |
| TWD-002 | `source.py` CLI module does not import `SourceIngestService` | Valid | `TestInvWatchDelegates001::test_twd_002_no_ingest_service_import` |
| TWD-003 | `source.py` CLI module does not import threading/timer primitives | Valid | `TestInvWatchDelegates001::test_twd_003_no_timer_import` |
| TWD-004 | Watch CLI command calls `SourceWatchService` workflow entry point | Valid | `TestInvWatchDelegates001::test_twd_004_delegates_to_workflow` |
| TWD-005 | `SourceWatchService` resides in `workflows/` package | Valid | `TestInvWatchDelegates001::test_twd_005_service_in_workflows` |

### INV-WATCH-DEBOUNCE-001

| ID | Scenario | Expected | Test |
|----|----------|----------|------|
| TWDB-001 | 10 file events within 1s, debounce=2s | Exactly 1 `ingest_source()` call after 2s | `TestInvWatchDebounce001::test_twdb_001_burst_debounced` |
| TWDB-002 | 2 events separated by < debounce interval | Timer resets, 1 `ingest_source()` call after last event + debounce | `TestInvWatchDebounce001::test_twdb_002_timer_reset` |
| TWDB-003 | 2 events separated by > debounce interval | 2 separate `ingest_source()` calls | `TestInvWatchDebounce001::test_twdb_003_separate_triggers` |
| TWDB-004 | Debounce interval < 1 second | Rejected: minimum debounce is 1s | `TestInvWatchDebounce001::test_twdb_004_minimum_debounce_enforced` |
| TWDB-005 | Ingest failure during debounce cycle | Error logged, returns to watching state, no crash | `TestInvWatchDebounce001::test_twdb_005_ingest_failure_recovers` |
