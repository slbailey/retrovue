# LAW-TIMELINE

## Constitutional Principle

Schedule defines boundary timing.

Content length, decoder EOF, or frame exhaustion do not redefine scheduled boundaries.

A boundary occurs when the schedule says it occurs.

## Implications

- EOF before boundary creates content deficit, not early boundary.
- Frame count is planning metadata, not timing authority.
- Segment transitions are time-authoritative, not content-authoritative.

## Violation

Switching because content ended rather than because the boundary time was reached.