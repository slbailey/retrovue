# INV-TRAFFIC-LATE-BIND-001: Traffic Fill Occurs at Feed Time, Not Compile Time

**Classification:** INVARIANT (Timing)
**Owner:**  in 
**Status:** ACTIVE (replaces compile-time fill in )
**Created:** 2026-02-18

---

## Definition

Traffic fill -- commercial selection, break filling, cooldown evaluation -- MUST
occur at **feed time** (~30 minutes before air), not at compile time (hours ahead).

 MUST produce blocks with empty filler
placeholders.  MUST fill those placeholders
with concrete interstitial assets before feeding the block to AIR.

---

## Rationale

When traffic fill happens at compile time:

1. **Cooldowns are stale.** Cooldowns are evaluated hours before the asset airs.
   An asset that aired 30 minutes ago may have a 60-minute cooldown, but compile-time
   evaluation (4 hours earlier) sees it as available and schedules it again.
2. **Pulled assets cannot be removed.** If a commercial is pulled from rotation after
   the schedule is compiled, it remains scheduled because the URI is already baked in.
3. **Over-rotation is invisible.** Daily-cap enforcement at compile time does not account
   for plays that occurred since compilation.

Feed-time fill solves all three: cooldowns, pulled assets, and caps are evaluated
against the actual play history at the moment the block enters the AIR queue.

---

## Compile-Time Contract (DslScheduleService)

 calls  and produces
 objects. Each ad break placeholder MUST be a single segment:

    segment_type = "filler"
    asset_uri = ""            # Empty URI = unfilled placeholder
    asset_start_offset_ms = 0
    segment_duration_ms = <break_ms>  # Allocated break duration preserved

 MUST NOT call  with a real .

The  table stores this unfilled schedule.

---

## Feed-Time Contract (BlockPlanProducer)

 MUST:

1. Open a fresh DB session.
2. Create a  for  (the channel slug).
3. Call .
4. Persist the filled block to .
5. Write  entries for each commercial in the filled block.
6. Call  to send to AIR.
7. Close the DB session.

On any error during fill: fall back to ,
persist the static-filled block, and feed. Never halt playout for traffic fill failure.

---

## Invariant Conditions

| Condition | Required state |
|-----------|---------------|
|  for a block | Has  for all filler segments |
|  for the same block | Has concrete  for all segments |
|  | MUST NOT import or call  |
|  | MUST call  before  |
| Cooldown evaluation | MUST occur inside , not  |

---

## Test Coverage

| Test | What it proves |
|------|---------------|
|  | DslScheduleService leaves asset_uri empty |
|  | Feed-time fill resolves real URIs |
|  | asset_library=None fallback works |
|  | Cooldown logged after compile => excluded at fill |

---

## See Also

- 
- 
- 
-  
-  
-  
