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
TODO

## Enforcement Evidence
TODO
