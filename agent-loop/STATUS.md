# STATUS.md — Agent Loop Handshake

**Current Status:** IDLE
**Last updated by:** RetrovueBot
**Timestamp:** 2026-03-30T21:41:00Z

---

## Status Values

| Value | Meaning |
|-------|---------|
| IDLE | No active task. Ready for next instruction. |
| TASK_READY | RetrovueBot has written NEXT_INSTRUCTION.md. Waiting for PoodadooBot to pick up. |
| IN_PROGRESS | PoodadooBot is working on the task. |
| DONE | PoodadooBot has finished. Results in EXECUTION_STATE.md. |
| BLOCKED | PoodadooBot hit an architectural decision point. Needs RetrovueBot guidance. See EXECUTION_STATE.md. |
| ERROR | PoodadooBot encountered an unrecoverable error. See EXECUTION_STATE.md. |

---

## Protocol

### RetrovueBot (Architect) responsibilities:
1. Write NEXT_INSTRUCTION.md with full task spec
2. Set STATUS = TASK_READY
3. Send a short sessions_send ping to PoodadooBot: New task ready in agent-loop
4. Poll this file every 60-90s via SSH until status = DONE, BLOCKED, or ERROR
5. If STATUS stays TASK_READY for >5 min, re-send the ping (do NOT rewrite the task)
6. After reading DONE results, set STATUS = IDLE before writing next task

### PoodadooBot (Engineer) responsibilities:
1. On receiving ping (or on startup), check STATUS.md
2. If TASK_READY: set STATUS = IN_PROGRESS, then read NEXT_INSTRUCTION.md
3. Do the work. Update EXECUTION_STATE.md with findings/results.
4. On completion: set STATUS = DONE
5. On architectural blocker: set STATUS = BLOCKED, explain in EXECUTION_STATE.md
6. On crash/restart: re-read NEXT_INSTRUCTION.md if STATUS = IN_PROGRESS (self-recovery)

### Ping format (sessions_send message):
agent-loop: new task ready. Check /opt/retrovue/agent-loop/STATUS.md

### Stale detection:
- TASK_READY for >5 min without IN_PROGRESS → re-ping
- IN_PROGRESS for >20 min without update → RetrovueBot may query PoodadooBot directly
