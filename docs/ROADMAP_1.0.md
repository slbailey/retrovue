# RetroVue 1.0 Roadmap

> A deterministic, observable, operator-driven broadcast system — not a feature-complete media platform.

---

## Where We Are (April 2026)

RetroVue is in **mid-development**. Phase A — "Proof of Broadcast Reality" — is the gate that everything else depends on. Until the runtime produces correct, deterministic MPEG-TS output over sustained periods, no higher-level feature matters.

Work on later phases has progressed opportunistically (scheduling APIs, asset ingest, stress tests, early UI all exist), but **Phase A must close before 1.0 can be sequenced.**

### Progress at a Glance

| Phase | Name | Status | Completion | Notes |
|-------|------|--------|------------|-------|
| **A** | Proof of Broadcast Reality | **In Progress** | ~60% | Muxing pipeline proven (EncoderPipeline + MuxInterleaver); TSMuxer stub deletion pending; validation pending |
| **B1** | Schedule Core | Mostly Done | ~85% | Publish/lock REST endpoints remaining |
| **B2** | Schedule Intelligence | Early | ~20% | Depends on C |
| **C** | Asset Management | Mostly Done | ~75% | REST write endpoints remaining |
| **D** | Reporting & Monitoring | Partial | ~30% | Infrastructure exists; no query APIs |
| **E** | Operator UI | Frozen | ~25% | **No new UI work until Phase A exit criteria pass** |
| **F** | Production Hardening | Partial | ~35% | Blocked on Phase A completion |

### What Works Today

* **Scheduling pipeline**: SchedulePlan → ScheduleDay → ExecutionEntry (11 invariants enforced)
* **Schedule REST API**: Full CRUD for plans and zones, validation, zone presets
* **Asset ingest**: Plex and filesystem importers, probing, enrichment, eligibility checks
* **Runtime playout**: ProgramDirector → ChannelManager → AIR (gRPC) → MPEG-TS bytes
* **HLS delivery**: In-memory SegmentRing + HlsSegmenter (INV-HLS-NO-DISK-IO-001)
* **Encoding pipeline**: Full FFmpeg H.264 + AAC encoder (EncoderPipeline, 2,479 lines) with MuxInterleaver for DTS-order packet interleaving
* **BlockPlan execution**: 2-block window model with validator and continuous feed
* **Operator CLI**: 13+ command modules covering channels, schedules, assets, runtime
* **Concurrent viewers**: Thread-safe join/leave tested with 100+ concurrent viewers
* **Prometheus metrics**: Feed controller telemetry, prefeed/switch lead time, queue depth
* **Early UI**: Schedule builder, EPG guide, studio interstitial tagger, player (HTMX + Tailwind)
* **Database**: PostgreSQL with Alembic migrations, Library/Broadcast domain split
* **Contracts**: 11 laws, 40+ invariants, knowledge graph, audit trail
* **524+ test files** across Core and AIR

---

## 🚧 Current Execution Focus (Next 2–3 Weeks)

If you only have 10 hours, this is what moves the system forward the most.

### Must Do

1. **Delete TSMuxer stub and clean up references** — TSMuxer.cpp is a dead placeholder (every method is a no-op/TODO). EncoderPipeline (2,479 lines) + MuxInterleaver is the sole mux authority. Remove TSMuxer.h, TSMuxer.cpp, StubMuxer.h, and the dead `muxer_` member in MpegTSPlayoutSink. This eliminates the competing mux path and resolves the INV-NO-GHOST-METHODS-001 violation.
2. **Eliminate the last `datetime.now()` leak** — `MasterClock._resolve_timezone()` line 156 in `runtime/clock.py` has a bare `datetime.now()` in the timezone fallback path. Isolated but contractually wrong.
3. **Run a 4-hour continuous playout test** — Validate: no gaps, stable segment cadence, correct offsets, no buffer underruns.
4. **Ensure correlation IDs cover playout trace logs** — Current coverage is ~95% (intentionally scoped per INV-LIFECYCLE-OBSERVABILITY-001). Verify that a 4-hour run produces a fully traceable event chain from schedule resolution to HLS viewer.

### Should Do (Before Long Runs)

5. **Pull forward basic observability from Phase D** — Before attempting 12-hour tests, ensure:
   - Correlation IDs are 100% propagated on all critical paths
   - Structured playout trace logs exist for every program transition
   - Minimal "why did this air" logging at decision time (not after the fact)
6. **Validate concurrent viewer correctness during sustained playout** — Multiple viewers joining at different times during a 4-hour run must all receive valid segments.

### Do Not Do Yet

- No new UI work (Phase E is frozen until Phase A exits)
- No new Phase B2 intelligence features
- No deployment docs or runbook (premature until runtime is proven)

---

## What Blocks 1.0

| # | Blocker | Phase | Severity | Current State |
|---|---------|-------|----------|---------------|
| 1 | **TSMuxer stub deletion** | A | **Medium** | Decision made: delete TSMuxer stub. EncoderPipeline is sole mux authority. Stub removal + reference cleanup remaining |
| 2 | **Sustained playout validation** | A | **Critical** | No 4-hour+ test run completed yet |
| 3 | **Clock authority leak** | A | Low | 1 remaining bare `datetime.now()` in timezone fallback (clock.py:156) |
| 4 | **Schedule publish/lock REST endpoints** | B1 | Medium | State machine exists internally; no REST surface |
| 5 | **As-run and compliance query APIs** | D | Medium | Logging infrastructure exists; no query API |
| 6 | **Deployment documentation** | F | Medium | Build scripts exist; no production setup guide |

---

## Phase Details

### Phase A: Proof of Broadcast Reality — In Progress (~60%)

**Goal**: Prove broadcast-grade correctness — deterministic, gap-free, observable playout over sustained periods.

This phase is the entire viability of the system. If muxing + timing isn't rock solid, everything above it is illusion.

| Work Item | Status | Notes |
|-----------|--------|-------|
| Encoding pipeline (FFmpeg H.264 + AAC) | **Done** | EncoderPipeline.cpp (2,479 lines), MuxInterleaver for DTS-order interleaving |
| Delete TSMuxer stub and clean references | **Not Done** | Decision: EncoderPipeline is sole mux authority (formally declared in AirArchitectureReference). Remove TSMuxer.h/.cpp, StubMuxer.h, dead muxer_ member in MpegTSPlayoutSink |
| Remove legacy disk-based HLS stack | **Done** | SegmentRing + HlsSegmenter only; INV-HLS-NO-DISK-IO-001 enforced |
| Complete correlation ID propagation | **Done** | 5 runtime modules carry session_id; channel-scoped events use channel_id per INV-LIFECYCLE-OBSERVABILITY-001 design |
| Fix remaining clock authority leaks | **Nearly Done** | 1 remaining: MasterClock._resolve_timezone() fallback path (clock.py:156) |
| Clean ghost method stubs | **Partial** | Base class templates acceptable; no critical runtime violations found |
| BlockPlan queue executor | **Done** | Full validator + 2-block window model in PlayoutSession.seed()/feed() |
| Viewer join under load | **Done** | 100+ concurrent viewer tests, churn tests, SegmentRing concurrency |
| **Basic observability (pulled from Phase D)** | **Partial** | Prometheus metrics exist; need structured playout trace logs and "why did this air" logging before long runs |

**Exit Criteria (Broadcast-Grade)**: All existing invariants pass. Zero known architectural violations. Plus:

* Continuous playout: minimum 4–6 hours sustained, target 12+ hours, no manual intervention
* No buffer underruns during steady-state operation
* No segment gaps or discontinuities in HLS output over the entire test duration
* Deterministic segment cadence: no drift over time; timing stable within tolerance
* Channel timeline integrity preserved across program transitions and break boundaries
* Full observability: end-to-end playout trace from schedule to HLS viewer with correlation IDs
* Concurrent viewer correctness: multiple viewers joining at different times receive valid segments

**Remaining work**: TSMuxer stub deletion is straightforward cleanup (not integration — the decision is made). Clock leak is a one-line fix. Observability trace logs needed before attempting 12-hour runs.

---

### Phase B1: Schedule Core — Mostly Done (~85%)

**Goal**: Operators can create, validate, publish, and execute schedules through a structured API workflow.

| Work Item | Status | Notes |
|-----------|--------|-------|
| Schedule creation API (REST) | **Done** | Full CRUD at /api/scheduling/channels/{id}/plans |
| Schedule validation endpoint | **Done** | Zone coverage validation with asset eligibility checks |
| Publish / lock / revise lifecycle | **Partial** | ScheduleRevision state machine exists (draft → active → superseded) but no REST endpoints for explicit publish/lock |
| Future-window mutation API | **Done** | Zone CRUD + zone presets API |

**Remaining work**: Expose publish/lock operations as explicit REST endpoints.

---

### Phase B2: Schedule Intelligence — Early (~20%)

**Goal**: Automation features that enhance schedules built in B1.

| Work Item | Status | Notes |
|-----------|--------|-------|
| Virtual asset expansion | **Not Started** | Referenced in contracts as TODO; no implementation |
| Break / interstitial slot management | **Partial** | Infrastructure exists (break_structure.py, traffic_manager.py, interstitial enricher); not API-exposed |
| Schedule templates / cloning | **Early** | SchedulePlanLabel exists for grouping; no REST endpoints |
| Channel identity layer | **Partial** | Channel model has slug, title, kind, programming_day_start; no branding API |

**Depends on**: Phase C asset metadata for virtual asset expansion and break fill pools.

---

### Phase C: Asset Management — Mostly Done (~75%)

**Goal**: Asset lifecycle from discovery through eligibility — scoped to what scheduling requires.

| Work Item | Status | Notes |
|-----------|--------|-------|
| Asset CRUD API (REST) | **Partial** | Listing + filtering at /api/scheduling/assets; no POST/PUT/DELETE endpoints (CLI only) |
| Asset eligibility visibility | **Done** | state="ready" AND approved_for_broadcast=true; eligibility checker validates |
| Basic relationships (series → episode) | **Done** | Editorial metadata in AssetEditorial.payload (JSONB): series_title, season_number, episode_number |
| Single primary source ingest | **Done** | Plex importer (full) + filesystem importer (glob patterns, tag inference) |

**Explicitly deferred (post-1.0)**: Full QC workflow, deep container hierarchies, 3+ source ingest, complex enrichment plugins, sidecar metadata import at scale.

**Remaining work**: Asset write endpoints (create/update/delete) via REST.

---

### Phase D: Reporting, Monitoring & Decision Trace — Partial (~30%)

**Goal**: Production-grade observability, compliance reporting, and the ability to answer *why* something aired.

> **Note**: Basic observability (correlation IDs, structured trace logs) has been pulled forward into Phase A exit criteria. Phase D covers the full reporting API surface.

| Work Item | Status | Notes |
|-----------|--------|-------|
| As-run report API | **Partial** | JSONL logging to /opt/retrovue/data/logs/asrun/; CLI doctor/validation; no REST query API |
| Schedule compliance report | **Not Started** | No implementation found |
| Channel health API | **Early** | ChannelMetricsSample collects viewer_count, producer_state, etc.; no REST endpoint |
| Structured metrics export (Prometheus) | **Done** | Gauges/Histograms/Counters for feed controller telemetry |
| OpenTelemetry integration | **Not Started** | — |
| Alert rules & thresholds | **Not Started** | — |
| EPG accuracy report | **Not Started** | — |
| System dashboard data API | **Not Started** | — |
| Playback Decision Trace | **Partial** | Evidence server exists; not exposed as queryable API |

**Playback Decision Trace design** (unchanged): Append-only persisted event model — not computed on demand via replay. Events written at decision time (schedule resolution, asset selection, fallback, break fill). Immutable once written. Read-only queries over the event log, filtered by channel, time range, or aired segment.

**Remaining work**: REST APIs to expose existing data (as-run, health, decision trace), plus new compliance/accuracy reporting.

---

### Phase E: Operator UI — Frozen (~25%)

**Goal**: Web-based interface for technical operators — exposing system truth with clarity and correctness.

> ⛔ **No new UI work until Phase A exit criteria pass.** UI creates false progress dopamine — schedule builders and EPG views look real but prove nothing about runtime correctness.

| Work Item | Status | Notes |
|-----------|--------|-------|
| UI technology selection | **Done** | HTMX + Tailwind CSS (server-rendered via FastAPI + Jinja2) |
| Authentication & authorization | **Not Started** | — |
| Schedule builder UI | **Done** | TV Guide–inspired grid editor (679 lines) |
| Asset library browser | **Not Started** | — |
| Channel monitoring dashboard | **Not Started** | — |
| As-run & compliance viewer | **Not Started** | Depends on Phase D APIs |
| Decision trace viewer | **Not Started** | Depends on Phase D APIs |
| EPG preview | **Done** | EPG guide view (805 lines) |
| System health overview | **Not Started** | — |
| Operator actions (emergency stop, override) | **Not Started** | — |

**Design guidance**: 1.0 UI = technical/power operator interface. Prioritize clarity over polish. All UI surfaces consume APIs from B1/B2/C/D — no UI-only logic.

**Remaining work**: Auth, asset browser, monitoring dashboard, reporting views, operator actions. All blocked on Phase A completion.

---

### Phase F: Production Hardening, Recovery & 1.0 Polish — Partial (~35%)

**Goal**: Stability, recovery correctness, and operational confidence for production release.

| Work Item | Status | Notes |
|-----------|--------|-------|
| Multi-channel stress testing | **Done** | stress_test_channels.sh: N concurrent consumers, CPU/backpressure monitoring |
| Graceful degradation & recovery | **Partial** | Contract tests for stale ring recovery, cold start connect |
| Cold start during active broadcast | **Done** | test_hls_cold_start_connect.py |
| System restart mid-playout | **Done** | test_hls_stale_ring_recovery.py |
| Channel recovery validation | **Partial** | Lifecycle contract tests exist; no 72-hour sustained validation yet |
| Reattachment to correct broadcast position | **Partial** | Clock authority resume tested; full validation pending |
| Backup & restore procedures | **Not Started** | — |
| Deployment documentation | **Early** | Build scripts exist; no production setup guide |
| Operator runbook | **Not Started** | — |
| Performance profiling & optimization | **Not Started** | — |
| Security audit | **Not Started** | — |
| Configuration validation | **Not Started** | — |
| Log rotation & retention | **Not Started** | — |

**Success Metrics (72-hour stability run)**:

| Metric | Target | Failure Condition |
|--------|--------|-------------------|
| CPU per channel (steady state) | ≤ 1 core equivalent | Sustained > 1.5 cores for > 60s |
| Memory per channel | ≤ 512 MB resident | RSS exceeds 768 MB at any point |
| Segment generation latency | ≤ 200ms p99 | p99 exceeds 500ms in any 10-minute window |
| Segment gap rate | 0 gaps | Any gap detected |
| Buffer underrun rate | 0 underruns (steady state) | Any underrun outside of startup window |
| Error rate (steady state) | 0 errors | Any unrecoverable error |
| Recovery time (restart/crash) | Correct output within 10s | First valid segment > 10s after restart |

**Remaining work**: 72-hour stability run, deployment docs, runbook, security audit, performance profiling.

---

## Dependency Graph

```
Phase A (Proof of Broadcast Reality)  ◄── CURRENT PRIORITY
    |
    v
Phase B1 (Schedule Core) ----------+       ← mostly done
    |                               |
    v                               |
Phase B2 (Schedule Intelligence) <--+--> Phase C (Asset Management)  ← mostly done
    |                                       |
    +---------------------------------------+
    |
    v
Phase D (Reporting, Monitoring & Decision Trace)
    |                ▲
    |                | basic observability pulled forward into Phase A
    v
Phase E (Operator UI)  ◄── FROZEN until Phase A exits
    |
    v
Phase F (Production Hardening, Recovery & 1.0)
```

* **A** must complete first — TSMuxer stub cleanup and sustained playout validation are the gates.
* **B1** is mostly done; publish/lock REST endpoints are the remaining gap.
* **B1** and **C** have been developed in parallel (both mostly done).
* **B2** depends on C for virtual asset expansion and break fill pools — B2 is early.
* **D** depends on B1, B2, and C for the data it reports on — basic observability pulled into Phase A.
* **E** is frozen — no new UI work until Phase A exit criteria pass.
* **F** has test infrastructure but the 72-hour stability run and ops docs are pending.

---

## Out of Scope for 1.0

* Independent Audio Servicing Pipeline — Phase 2+
* Linear-to-Library QR Bridge — Concept only
* Distributed Playout Workers — Single-node first
* Deterministic Playout Test Endpoint — QA tooling
* Continuity Announcer (AI voice) — Requires custom iFrameEnricher
* Waterbug/Lower-Third Overlays — iFrameEnricher expansion
* Diagnostic Slate Overlay — NOC tooling
* DASH support — HLS only
* DRM/content protection — Not required for personal media server
* Adaptive bitrate (ABR) — Single bitrate
* Full QC workflow — Deferred from Phase C
* Deep container hierarchies — Deferred from Phase C
* Extensive multi-source ingest (3+ sources) — Deferred from Phase C
* Complex enrichment plugin system — Deferred from Phase C
* Non-technical operator UX — 1.0 targets technical/power operators only

---

## Key Decisions Needed

1. **Auth model**: Simple API keys? OAuth? OIDC? Affects Phase E and production deployment.
2. **Multi-channel target for 1.0**: How many concurrent channels must be stable? (Suggested: 5–10)
3. **Alert delivery**: Email? Webhook? In-UI only? Affects Phase D scope.

---

## Guiding Principles

* **Contracts define outcomes, not implementation**: Every new capability gets an invariant before code.
* **APIs precede UI**: All Phase E work consumes APIs built in B1/B2/C/D. No UI-only logic.
* **Single authority per domain**: No new work introduces a second decision-maker for any domain.
* **No feature introduces competing decision logic**: Every addition must name its authority domain.
* **Complexity must be justified or removed**: Prefer removal over layering.
* **Broadcast model**: RetroVue simulates real broadcast. No VOD, no rewind, no catch-up.
* **Prove runtime before polish**: No UI or intelligence features until broadcast reality is proven.
