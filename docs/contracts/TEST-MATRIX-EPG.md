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
| TEPG-DT-002 | EPG event fields vs source ProgramEvent | Asset fields match source ProgramEvent | `TestInvEpgDerivationTraceable001::test_event_fields_match_source` |

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
