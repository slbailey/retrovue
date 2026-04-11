# INV-TIME-AUTHORITY-SINGLE-SOURCE

## Behavioral Guarantee
There is exactly one time authority in the system. Epoch MUST be set exactly once per session via `TrySetEpochOnce`. PREVIEW role MUST NOT set epoch. PTS is derived as epoch + offset; no subsystem maintains an independent CT counter. Session reset unlocks epoch for one new set.

## Authority Model
`MasterClock` owns the session epoch. Producer owns CT. Mux derives PTS from producer CT plus offset. Mux does not maintain local CT counters.

## Boundary / Constraint
`TrySetEpochOnce` MUST succeed on first LIVE call and reject all subsequent calls within the same session. PREVIEW role MUST always be rejected. `scheduled_to_utc_us(offset)` MUST return `epoch + offset` (derivation, not independent counter). `ResetEpochForNewSession` MUST unlock epoch for one new set.

## Violation
Duplicate epoch set accepted within a session; PREVIEW role sets epoch; local CT counter maintained by mux; PTS used as scheduling authority instead of derivation. MUST be logged.

## Derives From
`LAW-CLOCK`

## Required Tests
- `runtime/tests/contracts/BlockPlan/SharedInvTimeAuthorityContractTests.cpp` (`Compliant_EpochSetOnce_SecondSetRejected`) — first TrySetEpochOnce succeeds, second rejected, epoch value unchanged
- `runtime/tests/contracts/BlockPlan/SharedInvTimeAuthorityContractTests.cpp` (`Compliant_PreviewRoleAlwaysRejected`) — PREVIEW role always rejected, epoch not locked
- `runtime/tests/contracts/BlockPlan/SharedInvTimeAuthorityContractTests.cpp` (`Compliant_PtsDerivedFromEpochPlusOffset`) — PTS=0 maps to epoch, PTS=1s maps to epoch+1s
- `runtime/tests/contracts/BlockPlan/SharedInvTimeAuthorityContractTests.cpp` (`Compliant_SessionResetAllowsNewEpoch`) — reset unlocks, new epoch allowed, value updated

## Enforcement Evidence
TODO
