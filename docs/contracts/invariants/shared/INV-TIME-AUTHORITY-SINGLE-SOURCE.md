# INV-TIME-AUTHORITY-SINGLE-SOURCE

## Behavioral Guarantee
There is exactly one time authority in the system. Audio is PCR master. Producer (TimelineController) is CT authority. Mux derives PTS from producer CT plus offset. Mux does not maintain local CT counters. CT is not reset on attach.

## Authority Model
Audio owns PCR. Producer owns CT. Mux is pass-through for time; it does not invent or reset presentation time.

## Boundary / Constraint
Mux MUST use producer-supplied CT only. No local CT; no reset on attach. PTS is derived (CT + offset), not used as scheduling authority.

## Violation
Video drives PCR. Mux resets CT. Mux maintains independent clock. PTS used as scheduling authority. MUST be logged.

## Required Tests
- `pkg/air/tests/contracts/MasterClock/MasterClockContractTests.cpp`
- `pkg/air/tests/contracts/TimelineController/TimelineControllerContractTests.cpp`

## Enforcement Evidence

- `MasterClock::TrySetEpochOnce()` prevents epoch drift — epoch can only be set once per session; subsequent attempts are rejected, ensuring a single time origin.
- `TimelineController` owns CT (composition time); all timing decisions derive from this single authority. No subsystem maintains an independent CT counter.
- `EncoderPipeline` accepts pre-computed CT from the producer — it does not derive, reset, or maintain local CT counters. PTS is computed as `CT + offset`, not used as a scheduling authority.
- Contract tests: `MasterClockContractTests.cpp` validates single-epoch enforcement and rejects duplicate epoch sets. `TimelineControllerContractTests.cpp` validates CT authority and no local counter drift.
