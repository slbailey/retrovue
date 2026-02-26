# LAW-CLOCK

## Constitutional Principle

There is exactly one authoritative time source for playout.

All timeline decisions, switching deadlines, and pacing behavior derive from this single clock authority.

No subsystem may invent, reset, or locally reinterpret time.

## Implications

- Producer CT is authoritative.
- Sink does not synthesize alternate clock domains.
- Switch deadlines are evaluated against the authoritative clock only.
- Attach/detach events do not reset clock authority.
- Frame completion never overrides clock authority.

## Violation

Any subsystem that:
- Resets time on attach
- Creates a secondary clock domain
- Delays a declared boundary due to frame availability
- Uses local wall-clock as authority

is in violation of LAW-CLOCK.
