# Test Matrix — EPG Invariants

**Status:** Active
**Test file:** `pkg/core/tests/contracts/test_epg_invariants.py`

---

## Section 1: Temporal Integrity

### INV-EPG-NO-OVERLAP-001

| ID | Scenario | Expected | Test |
|----|----------|----------|------|
| TEPG-NO-001 | Single day, 4 contiguous programs | No consecutive pair overlaps | `TestInvEpgNoOverlap001::test_single_day_no_overlap` |
| TEPG-NO-002 | Two adjacent broadcast days queried together | No overlap across day boundary | `TestInvEpgNoOverlap001::test_cross_day_boundary_no_overlap` |

### INV-EPG-NO-GAP-001

| ID | Scenario | Expected | Test |
|----|----------|----------|------|
| TEPG-NG-001 | Full broadcast day with 4 programs | Consecutive events temporally adjacent | `TestInvEpgNoGap001::test_full_day_no_gaps` |
| TEPG-NG-002 | Partial query within a broadcast day | No gaps within queried range | `TestInvEpgNoGap001::test_partial_query_no_gaps` |

### INV-EPG-BROADCAST-DAY-BOUNDED-001

| ID | Scenario | Expected | Test |
|----|----------|----------|------|
| TEPG-BD-001 | Daytime programs (06:00–18:00) | All events within broadcast day window | `TestInvEpgBroadcastDayBounded001::test_events_within_broadcast_day` |
| TEPG-BD-002 | Late-night programs (after midnight, before 06:00) | Events still within prior broadcast day window | `TestInvEpgBroadcastDayBounded001::test_late_night_within_broadcast_day` |

---

## Section 2: Content Integrity

### INV-EPG-FILLER-INVISIBLE-001

| ID | Scenario | Expected | Test |
|----|----------|----------|------|
| TEPG-FI-001 | Programs with content shorter than grid block | No EPG event references filler asset | `TestInvEpgFillerInvisible001::test_filler_not_in_epg` |

### INV-EPG-IDENTITY-STABLE-001

| ID | Scenario | Expected | Test |
|----|----------|----------|------|
| TEPG-IS-001 | Two identical queries after resolution | All identity fields match between queries | `TestInvEpgIdentityStable001::test_identity_stable_across_queries` |

### INV-EPG-DERIVATION-TRACEABLE-001

| ID | Scenario | Expected | Test |
|----|----------|----------|------|
| TEPG-DT-001 | EPG events from resolved day | Every event's programming_day_date matches source | `TestInvEpgDerivationTraceable001::test_every_event_traces_to_resolved_day` |
| TEPG-DT-002 | EPG event fields vs source ScheduleItem | Asset fields match source ScheduleItem | `TestInvEpgDerivationTraceable001::test_event_fields_match_source` |

---

## Section 3: Availability & Accuracy

### INV-EPG-VIEWER-INDEPENDENT-001

| ID | Scenario | Expected | Test |
|----|----------|----------|------|
| TEPG-VI-001 | Query future resolved day, no viewers | Non-empty EPG result returned | `TestInvEpgViewerIndependent001::test_epg_available_without_viewers` |

### INV-EPG-PROGRAM-CONTINUITY-001

| ID | Scenario | Expected | Test |
|----|----------|----------|------|
| TEPG-PC-001 | 90-min movie spanning 3 blocks (30-min grid) | Single EPGEvent with 90-min duration | `TestInvEpgProgramContinuity001::test_multiblock_program_single_entry` |
| TEPG-PC-002 | 45-min program spanning 2 blocks | Single EPGEvent with 60-min grid duration | `TestInvEpgProgramContinuity001::test_two_block_span_single_event` |

---

## Section 4: Operational Non-Interference

### INV-EPG-NONAUTHORITATIVE-FOR-PLAYOUT-001 (structural enforcement)

| ID | Scenario | Expected | Test |
|----|----------|----------|------|
| TEPG-NB-001 | EPG handlers in ProgramDirector | All EPG handlers are plain `def` (not `async def`) | `TestEpgEndpointNonBlocking::test_epg_handlers_not_async_program_director` |
| TEPG-NB-002 | EPG handler in web/api/epg.py | Handler is plain `def` (not `async def`) | `TestEpgEndpointNonBlocking::test_epg_handler_not_async_web_api` |

---

## Section 5: Canonical Schedule Authority

### INV-EPG-READS-CANONICAL-SCHEDULE-001

**Test file:** `pkg/core/tests/contracts/runtime/test_inv_epg_reads_canonical.py`

| ID | Scenario | Expected | Test |
|----|----------|----------|------|
| TEPG-CAN-001 | EPG module AST inspection | No `compile_schedule` call in `/api/epg` handler | `TestInvEpgReadsCanonical001::test_epg_module_does_not_import_compile_schedule` |
| TEPG-CAN-002 | Canonical EPG with cached blocks | Returns cached `program_blocks` without calling `compile_schedule()` | `TestInvEpgReadsCanonical001::test_get_canonical_epg_returns_cached_blocks` |
| TEPG-CAN-003 | Canonical EPG with empty DB | Returns `None` when no cached schedule exists | `TestInvEpgReadsCanonical001::test_get_canonical_epg_returns_none_when_not_cached` |
| TEPG-CAN-004 | Carry-in block from previous day | Range overlap query includes block spanning day boundary | `TestInvEpgReadsCanonical001::test_get_canonical_epg_includes_carry_in_block` |

---

## Section 6: Duration Visibility & Formatting

### INV-EPG-DURATION-VISIBILITY-001

**Test file:** `pkg/core/tests/contracts/test_epg_duration_visibility.py`

| ID | Scenario | Expected | Test |
|----|----------|----------|------|
| TEPG-DV-001 | Grid-aligned 30min item (09:00–09:30) | `display_duration` is `null` | `TestInvEpgDurationVisibility001::test_grid_aligned_30min_not_shown` |
| TEPG-DV-002 | Grid-aligned 60min item (09:00–10:00) | `display_duration` is `null` | `TestInvEpgDurationVisibility001::test_grid_aligned_60min_not_shown` |
| TEPG-DV-003 | Grid-aligned 120min item (09:00–11:00) | `display_duration` is `null` | `TestInvEpgDurationVisibility001::test_grid_aligned_120min_not_shown` |
| TEPG-DV-004 | 2h 5m movie (09:00–11:05) | `display_duration` is `"2h 5m"` | `TestInvEpgDurationVisibility001::test_125min_shown_as_2h_5m` |
| TEPG-DV-005 | 89.5min item (09:00–10:29:30) rounds to 90min | `display_duration` is `null` (grid-aligned after rounding) | `TestInvEpgDurationVisibility001::test_89_5min_rounds_to_90_grid_aligned` |
| TEPG-DV-006 | 90.5min item (09:00–10:30:30) rounds to 91min | `display_duration` is `"1h 31m"` | `TestInvEpgDurationVisibility001::test_90_5min_rounds_to_91_shown` |
| TEPG-DV-007 | 45min item (09:00–09:45) | `display_duration` is `"45m"` | `TestInvEpgDurationVisibility001::test_45min_shown` |
| TEPG-DV-008 | 30min item off-grid (09:05–09:35) | `display_duration` is `"30m"` (grid disrupted) | `TestInvEpgDurationVisibility001::test_30min_off_grid_shown` |
| TEPG-DV-009 | All formatted outputs | No decimals in any `display_duration` value | `TestInvEpgDurationVisibility001::test_no_decimals_in_output` |
| TEPG-DV-010 | 90.5min movie in 120min grid slot | Content duration shown as `"1h 31m"` despite grid-aligned slot | `TestInvEpgDurationVisibility001::test_content_shorter_than_slot_shows_content_duration` |
| TEPG-DV-011 | Content fills slot exactly, both grid-aligned | `display_duration` is `null` | `TestInvEpgDurationVisibility001::test_content_equals_slot_grid_aligned` |
| TEPG-DV-012 | 90min content in 120min slot | Content grid-aligned (90%30==0), `display_duration` is `null` | `TestInvEpgDurationVisibility001::test_content_grid_aligned_in_larger_slot` |
| TEPG-DV-013 | TV episode (season != null) with non-grid duration | `display_duration` is `null` (episodes always suppressed) | `TestInvEpgDurationVisibility001::test_tv_episode_never_shows_duration` |
| TEPG-DV-014 | Movie (is_movie=True) with non-grid content duration | `display_duration` is `"1h 31m"` | `TestInvEpgDurationVisibility001::test_movie_no_season_shows_duration` |
| TEPG-DV-015 | TV episode that IS grid-aligned | Grid check passes, returns `null` | `TestInvEpgDurationVisibility001::test_tv_episode_grid_aligned_returns_none` |
