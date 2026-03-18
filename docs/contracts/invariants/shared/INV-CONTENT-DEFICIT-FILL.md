# INV-CONTENT-DEFICIT-FILL

## Behavioral Guarantee
When content is absent or exhausted, output MUST continue at real-time cadence without stall. The fill mechanism is authority-dependent: PadProducer (black video + silent audio) fills zero-content and PADDED_GAP deficits; hold-last (repeat of last decoded frame) bridges mid-block content EOF. At any tick, exactly one authority — content, hold-last, or pad — owns the output frame.

## Authority Model
PipelineManager owns the per-tick TAKE decision. `TAKE_PAD_ENTER` / `TAKE_PAD_EXIT` log lines are the observable authority transitions between content and pad.

## Boundary / Constraint
Output MUST NOT stall or break TS cadence due to content deficit. Each tick MUST be served by exactly one of: content frame, hold-last frame, or pad frame. `TAKE_PAD_ENTER` and `TAKE_PAD_EXIT` MUST form a proper alternating state machine (no double-ENTER, no EXIT without prior ENTER). `pad_frames_emitted_total + content_frames == continuous_frames_emitted_total` at all times.

## Violation
Output stall or TS cadence break due to content gap; overlapping frame authority (pad active during content playback, or content active during pad); unpaired `TAKE_PAD_ENTER` / `TAKE_PAD_EXIT` transitions. MUST be logged.

## Derives From
`LAW-LIVENESS`

## Required Tests
- `pkg/air/tests/contracts/BlockPlan/SharedInvContentDeficitFillContractTests.cpp` (`Compliant_ZeroContent_AllFrameFilledByPad`) — 100% deficit: all frames pad, `TAKE_PAD_ENTER` logged, `TAKE_PAD_EXIT` absent
- `pkg/air/tests/contracts/BlockPlan/SharedInvContentDeficitFillContractTests.cpp` (`Compliant_ContentPlusDeficit_NoContinuityGap`) — content active: pad_frames=0, no `TAKE_PAD_ENTER` during content window
- `pkg/air/tests/contracts/BlockPlan/SharedInvContentDeficitFillContractTests.cpp` (`Compliant_ContentEOFBeforeFence_OutputContinuous`) — mid-block EOF: hold-last bridges deficit, no `TAKE_PAD_ENTER`, pad_frames=0, total > content_frames
- `pkg/air/tests/contracts/BlockPlan/SharedInvContentDeficitFillContractTests.cpp` (`SingleAuthority_PadContentTransitionsArePaired`) — PADDED_GAP: pad fills deficit, `TAKE_PAD_ENTER`/`EXIT` alternating, pad+content==total

## Enforcement Evidence
TODO
