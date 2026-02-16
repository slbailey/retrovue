# Phase 04 – Runtime Integration & Telemetry

**Status:** Planned

## Objective
Wire the new compiled schedules, ads, and packaging into the live runtime (ScheduleService, ChannelManager, Air) with observability to ensure contracts hold during playout.

## Deliverables
1. ScheduleService ingestion path for compiled plans (feature-flagged rollout).
2. ChannelManager updates to push rich PlaylogSegments to Air.
3. Telemetry + AsRunLogger enhancements to confirm ad/promos aired as planned.
4. Prometheus/Grafana dashboards for schedule health.

## Key Tasks
- [ ] Extend ScheduleService to load compiled plans and expose playout horizons.
- [ ] Update gRPC protobufs if needed (versioned) for new segment metadata.
- [ ] Add runtime metrics + alerts (missing ads, packaging mismatches, compile failures).
- [ ] Write integration tests (maybe via docker-compose harness) simulating tune-in events.

## Next Up
Blocked until Phases 01–03 are implemented; use this file to capture integration findings once we get there.
