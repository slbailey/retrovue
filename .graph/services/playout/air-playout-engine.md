# AIR playout engine

**Domain:** playout  
**Slug:** `air-playout-engine`

## Responsibility

**Real-time execution**: decode, producer switching (preview/live), pacing, mux, emit TS into the sink Core attached—**one active session** at a time per process model.

## Owns vs reads

- **Owns:** frame timing, buffer policy, internal producers, PlayoutInstance execution truth.
- **Reads:** gRPC plans/BlockPlan feed from ChannelManager; does **not** read database schedules or EPG.

## Upstream inputs

`channel-manager` gRPC (`PlayoutControl` contract), attached stream handle.

## Downstream outputs

MPEG-TS bytes to sink; telemetry upward as designed.

## Must NOT do

- Query SchedulePlan, ScheduleDay, zones, or EPG.
- Accept direct commands from scheduling services (`INV-SCHEDULEMANAGER-NO-AIR-ACCESS-001`).

## Boundary

Core answers **what and when** in execution artifacts; AIR answers **how frames and bytes** behave in real time.
