# INV-CLOCK-OBLIGATIONS-OVERRIDE-001 — Clock obligations override block structure

Status: Invariant
Authority Level: Planning
Derived From: `LAW-CONTENT-AUTHORITY`, `LAW-GRID`, `LAW-CLOCK`

## Purpose

Protects `LAW-CONTENT-AUTHORITY` and `LAW-GRID` by ensuring that clock-scoped obligations (top-of-hour station IDs, legal IDs, daypart transitions) are honored at their wall-clock trigger times regardless of block structure. Without this guarantee, a station ID required by regulation at the top of every hour could be silently omitted when no commercial break happens to fall at that time.

## Guarantee

Clock obligations MUST be evaluated in a second compilation pass against absolute wall-clock time. When an obligation's trigger time falls within a block's time range, the obligation MUST be honored in that block. Obligation placement follows these rules:

1. If the trigger time falls within a break, the obligation MUST be inserted into that break, displacing Tier 4 fill per `INV-TIER-DISPLACEMENT-001`.
2. If the trigger time falls within primary content, the compiler MUST defer the obligation to the nearest eligible placement point. Eligible placement points are, in priority order: (a) the next existing break within the same block, (b) the block boundary (appended after the last segment). If no eligible point exists within the block, the obligation attaches to the next block boundary. The compiler MUST NOT insert a micro-break or split primary content to place an obligation.
3. Clock obligations MUST NOT cut, truncate, or shift primary content (`INV-MOVIE-PRIMARY-ATOMIC`).

Clock obligations are channel-global configuration, not per-template. Templates MAY declare which obligation types they participate in but MUST NOT suppress mandatory obligations.

## Preconditions

- First compilation pass has completed: all Tier 0-1 segments resolved, break positions determined.
- Channel YAML contains an `obligations:` section defining clock-scoped rules.
- Block boundaries and absolute wall-clock start times are known.

## Observability

A compiled schedule day where a mandatory obligation trigger time falls within a block's time range but no obligation segment appears in that block's `compiled_segments`. Observable via audit of compiled output against obligation config.

## Deterministic Testability

Given a channel config with `obligations: [{ type: station_id, interval_minutes: 60 }]` and a broadcast day with known block boundaries, the second compilation pass MUST produce identical obligation insertions on every compilation. Verify: obligation segment count matches expected trigger count; obligation positions respect safe-point rules; no obligation is omitted.

## Failure Semantics

**Planning fault.** The compiler failed to evaluate or insert a mandatory obligation. The compiled schedule is non-compliant with the channel's obligation configuration.

## Required Tests

- `server/tests/contracts/test_block_assembly_tiers.py`

## Enforcement Evidence

TODO
