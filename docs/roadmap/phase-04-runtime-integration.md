# Phase 04 – Runtime Integration & Telemetry

**Status:** ✅ Implemented (core integration complete; telemetry dashboards remaining)

## Objective
Wire the compiled schedules, ads, and packaging into the live runtime (ScheduleService, ChannelManager, Air) with observability to ensure contracts hold during playout.

## What Exists Today

### Schedule → Runtime Pipeline (DELIVERED)
- `DslScheduleService` loads compiled DSL plans and serves them to ChannelManager
- `HorizonBackedScheduleService` provides rolling schedule horizon
- `HorizonManager` extends EPG + execution horizons by day
- Schedule compilation happens on startup + rolling extension
- Catalog resolver loads 12,364 assets + 24,375 aliases from Plex DB

### ChannelManager → AIR Integration (DELIVERED)
- BlockPlan conversion from compiled schedule → gRPC `StartBlockPlanSession`
- Continuous block feeding via `FeedBlockPlan` + `SubscribeBlockEvents`
- Fence-based block timing with wall-clock discipline
- On-demand channel spinup (AIR subprocess per active channel)
- Segment-aware playback: content, filler, pad segments
- SeamPreparer for background preparation of segment/block transitions

### HLS Streaming (DELIVERED)
- `pkg/core/src/retrovue/streaming/hls_writer.py` — segments MPEG-TS into HLS
- SocketTsSource receives bytes from AIR via Unix domain socket
- On-demand: channel starts encoding only when first viewer joins
- Linger timeout: channel stays alive 20s after last viewer disconnects
- Multi-viewer fanout via ChannelStream

### Evidence / As-Run (DELIVERED)
- `ExecutionEvidence` gRPC streaming from AIR → Core
- Evidence types: hello, block_start, segment_start, channel_terminated
- `AsRunLogger` records actual playout events
- `AsRunReconciler` for plan-vs-actual comparison (contract + tests)

### Runtime Health (DELIVERED)
- ProgramDirector health-check loop for all active ChannelManagers
- Viewer lifecycle tracking (INV-VIEWER-LIFECYCLE-001/002)
- Producer teardown on last viewer disconnect
- Runway Min contract (INV-RUNWAY-MIN-001)

## Remaining Deliverables
1. **Prometheus metrics export** — NOT STARTED
2. **Grafana dashboards** — NOT STARTED
3. **Runtime alerts** — missing ads, packaging mismatches, compile failures — NOT STARTED
4. **CI integration tests** — docker-compose harness — NOT STARTED

## Open Tasks
- [x] ScheduleService ingestion of compiled DSL plans
- [x] ChannelManager BlockPlan feeding to AIR
- [x] HLS streaming with on-demand spinup
- [x] Evidence gRPC streaming (AIR → Core)
- [x] As-run logging + reconciliation
- [x] Multi-viewer fanout
- [x] On-demand channel lifecycle (start on first viewer, stop on last)
- [ ] Prometheus metrics endpoint
- [ ] Grafana dashboards for schedule health
- [ ] Runtime alerts (missing ads, compile failures)
- [ ] CI integration test harness (docker-compose)

## Next Up
Prometheus/Grafana once Phase 02 traffic manager is expanded.
