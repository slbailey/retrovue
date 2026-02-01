# Phase 1 Task Files

Individual task files for Cursor/AI-assisted implementation.

## Usage

1. Open one task file in Cursor
2. Use the task file as context for the AI
3. Implement exactly what the task specifies
4. Stop when the task is complete

## Task Files

### ProgramOutput (5 tasks)
| Task | Type | Rule |
|------|------|------|
| [P1-PO-001](P1-PO-001.md) | TEST | INV-STARVATION-FAILSAFE-001 |
| [P1-PO-002](P1-PO-002.md) | TEST | INV-P10-SINK-GATE |
| [P1-PO-003](P1-PO-003.md) | LOG | INV-P10-SINK-GATE |
| [P1-PO-004](P1-PO-004.md) | VERIFY | LAW-OUTPUT-LIVENESS |
| [P1-PO-005](P1-PO-005.md) | VERIFY | INV-AIR-CONTENT-BEFORE-PAD |

### EncoderPipeline (5 tasks)
| Task | Type | Rule |
|------|------|------|
| [P1-EP-001](P1-EP-001.md) | TEST | LAW-AUDIO-FORMAT |
| [P1-EP-002](P1-EP-002.md) | LOG | LAW-AUDIO-FORMAT |
| [P1-EP-003](P1-EP-003.md) | TEST | INV-AUDIO-HOUSE-FORMAT-001 |
| [P1-EP-004](P1-EP-004.md) | TEST | INV-ENCODER-NO-B-FRAMES-001 |
| [P1-EP-005](P1-EP-005.md) | VERIFY | INV-AIR-IDR-BEFORE-OUTPUT |

### MpegTSOutputSink (3 tasks)
| Task | Type | Rule |
|------|------|------|
| [P1-MS-001](P1-MS-001.md) | LOG | INV-P9-BOOT-LIVENESS |
| [P1-MS-002](P1-MS-002.md) | LOG | INV-P9-AUDIO-LIVENESS |
| [P1-MS-003](P1-MS-003.md) | VERIFY | LAW-VIDEO-DECODABILITY |

### PlayoutEngine (2 tasks)
| Task | Type | Rule |
|------|------|------|
| [P1-PE-001](P1-PE-001.md) | LOG | INV-P8-ZERO-FRAME-BOOTSTRAP |
| [P1-PE-002](P1-PE-002.md) | VERIFY | INV-P9-BOOTSTRAP-READY |

## Recommended Order

1. **VERIFY tasks first** — Confirm existing coverage before adding new
2. **LOG tasks second** — Low risk, immediate observability value
3. **TEST tasks last** — Require more implementation effort

## Cursor Prompt Template

```
You are implementing ONE atomic task.
Do not refactor, rename, or modify any unrelated code.
Do not combine tasks.
Do not add logs (unless task type is LOG).
Do not "improve" behavior.

@docs/contracts/tasks/phase1/P1-XX-NNN.md
```

## Completion Tracking

After completing a task:
1. Update [PHASE1_TASKS.md](../../PHASE1_TASKS.md) checklist
2. Commit with message: `feat(air): implement P1-XX-NNN <rule-id>`
