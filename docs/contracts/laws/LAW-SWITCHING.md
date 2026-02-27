# LAW-SWITCHING

## Constitutional Principle

Switches are deadline-authoritative and exactly-once.

A declared boundary must result in one and only one switch issuance.

## Implications

- No polling-based reissuance.
- No retry loops that re-evaluate past deadlines.
- Failure transitions must be explicit and terminal.

## Violation

Multiple switch attempts for the same boundary or delayed issuance beyond declared tolerance.