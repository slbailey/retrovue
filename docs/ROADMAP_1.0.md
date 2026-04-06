# RetroVue 1.0 Roadmap (Revised)

> A deterministic, observable, operator-driven broadcast system — not a feature-complete media platform.

## Current State Summary

RetroVue has a **strong architectural foundation**: strict Core/AIR separation, 40+ invariants, contracts-first development, comprehensive CLI, 495+ test files, and a well-defined knowledge graph. The system can schedule content, activate channels on viewer arrival, and stream MPEG-TS via HLS — but several critical subsystems remain incomplete, and there is no operator UI or reporting layer.

### What Works Today

* **Scheduling pipeline**: SchedulePlan → ScheduleDay → ExecutionEntry (11 invariants enforced)
* **Asset ingest**: Source → Container → Asset with probing, enrichment, and eligibility checks
* **Runtime playout**: ProgramDirector → ChannelManager → AIR (gRPC) → MPEG-TS bytes
* **HLS delivery**: In-memory SegmentRing + HlsSegmenter (INV-HLS-NO-DISK-IO-001)
* **Operator CLI**: 13+ command modules covering channels, schedules, assets, runtime
* **Database**: PostgreSQL with Alembic migrations, Library/Broadcast domain split
* **Contracts**: 11 laws, 40+ invariants, knowledge graph, audit trail

### Known Debt

* Legacy HLS stack remnants (old disk-based path identified in DEEP\_ANALYSIS.md)
* MPEG-TS muxer incomplete in AIR (TODO markers in TSMuxer.cpp)
* Correlation ID propagation partial
* Some clock authority leaks in non-critical paths (~85% enforced per audit)

---

## Roadmap Phases

### Phase A: Foundation Hardening (Prerequisites for 1.0)

**Goal**: Eliminate known architectural debt and prove broadcast-grade correctness over time — not just in a single execution path.

| Work Item                           | Domain  | Why                                                                 |
| ----------------------------------- | ------- | ------------------------------------------------------------------- |
| Complete MPEG-TS muxer in AIR       | Playout | Blocks real end-to-end TS output                                    |
| Remove legacy disk-based HLS stack  | Systems | Violates INV-HLS-NO-DISK-IO-001                                     |
| Complete correlation ID propagation | Systems | Required for production debugging (INV-LIFECYCLE-OBSERVABILITY-001) |
| Fix remaining clock authority leaks | Systems | PlaylistBuilderDaemon still uses bare datetime.now()                |
| Clean ghost method stubs            | Systems | INV-NO-GHOST-METHODS-001 compliance                                 |
| BlockPlan queue executor            | Playout | Required for continuous multi-block playout                         |
| **Viewer join under load**          | Systems | Concurrent viewer arrival is a critical activation path             |

**Exit Criteria (Broadcast-Grade)**:

All existing invariants pass. Zero known architectural violations. Plus:

* **Continuous playout**: Minimum 4-6 hours sustained, target 12+ hours, with no manual intervention
* **No buffer underruns** during steady-state operation
* **No segment gaps or discontinuities** in HLS output over the entire test duration
* **Deterministic segment cadence**: No drift over time; segment timing remains stable within tolerance
* **Channel timeline integrity**: Preserved across program transitions and break boundaries
* **Full observability**: End-to-end playout from schedule to HLS viewer with correlation IDs
* **Concurrent viewer correctness**: Multiple viewers joining at different times receive valid segments; SegmentRing correct under concurrent access; no segment starvation or race conditions

> Phase A proves: the system behaves correctly over time, not just in a single execution path — including under concurrent viewer load.

---

### Phase B1: Schedule Core (Correctness & Lifecycle)

**Goal**: Operators can create, validate, publish, and execute schedules through a structured API workflow with all invariants enforced — no automation features.

| Work Item                         | Domain     | Why                                                      |
| --------------------------------- | ---------- | -------------------------------------------------------- |
| Schedule creation API (REST)      | Core/HTTP  | Enables UI-driven and programmatic schedule building     |
| Schedule validation endpoint      | Core/HTTP  | Real-time feedback on grid violations, gaps, eligibility |
| Publish / lock / revise lifecycle | Core       | Formal schedule state machine (draft, published, locked) |
| Future-window mutation API        | Scheduling | Edit upcoming schedule without affecting locked entries  |

**Exit Criteria**:

* Operator can create, validate, publish, and execute a schedule deterministically via API
* All scheduling invariants enforced without any automation or fill features
* Schedule lifecycle transitions are auditable
* Locked schedules are immutable

---

### Phase B2: Schedule Intelligence (Automation & Fill Logic)

**Goal**: Automation features that enhance schedules built in B1, without violating B1 invariants.

| Work Item                            | Domain     | Why                                                     |
| ------------------------------------ | ---------- | ------------------------------------------------------- |
| Virtual asset expansion              | Scheduling | Series, playlists, and auto-fill pattern resolution     |
| Break / interstitial slot management | Scheduling | Tier-2 fill (bumpers, promos, IDs) integrated into grid |
| Schedule templates / cloning         | Scheduling | Reuse weekly patterns; day-part templates               |
| Channel identity layer               | Scheduling | Behaviorally relevant channel identity (see below)      |

**Channel Identity Layer**:

Channel identity is not just metadata — it is **behaviorally relevant**. In 1.0, channel identity influences:

* **Bumper selection**: Channel-specific station IDs and bumpers are selected based on identity linkage
* **Break fill pools**: Each channel can have its own interstitial pool, filtered by identity
* **Schedule flavor** (direction for post-1.0): Channel identity will inform day-part mood, genre weighting, and scheduling personality

For 1.0, this means: channel name, description, branding metadata, and bumper/ID pool linkage that the break fill resolver uses at publish time.

**Exit Criteria**:

* Automation features enhance schedules without violating B1 invariants
* Breaks and fills resolve deterministically
* Virtual assets expand to concrete entries at publish time
* Channel identity metadata is behaviorally connected: bumper selection and break fill pools respect channel identity
* B2 may begin after B1 but requires Phase C asset capabilities for full completion (virtual assets and break fill pools depend on asset metadata)

---

### Phase C: Asset Management (Broadcast Eligibility)

**Goal**: Asset lifecycle from discovery through eligibility — scoped to what scheduling requires, not a full media library platform.

| Work Item                               | Domain    | Why                                                                    |
| --------------------------------------- | --------- | ---------------------------------------------------------------------- |
| Asset CRUD API (REST)                   | Core/HTTP | Create, read, update, delete assets; search and filter                 |
| Asset eligibility visibility            | Core/HTTP | Surface why assets are or are not eligible for scheduling              |
| Basic relationships (series to episode) | Ingest    | Series, Season, Episode; movie to trailer                              |
| Single primary source ingest            | Ingest    | One well-supported source (Plex or filesystem); one secondary optional |

**Explicitly Deferred (post-1.0)**:

* Full QC workflow (probe review, manual approve/reject)
* Deep container hierarchies (nested organizational depth)
* Extensive multi-source ingest (3+ sources)
* Complex enrichment plugin system (pluggable TMDb/TVDb/custom)
* Sidecar metadata import at scale

**Exit Criteria**:

* Operator can discover, import, and manage assets through API
* Assets carry basic relational metadata (series to episode)
* Asset eligibility is visible and explainable (why eligible / not eligible)
* 1-2 sources supported end-to-end

> RetroVue is a broadcast system, not a media library platform.

---

### Phase D: Reporting, Monitoring & Decision Trace

**Goal**: Production-grade observability, compliance reporting, operational dashboards — and the ability to answer *why* something aired, not just *what* and *when*.

| Work Item                              | Domain     | Why                                                                           |
| -------------------------------------- | ---------- | ----------------------------------------------------------------------------- |
| As-run report API                      | Core/HTTP  | Query historical as-run data by channel, date range                           |
| Schedule compliance report             | Core/HTTP  | Compare scheduled vs. aired; flag deviations                                  |
| Channel health API                     | Core/HTTP  | Current state, buffer depth, viewer count, uptime                             |
| Structured metrics export (Prometheus) | Systems    | Core-side metrics to match AIR telemetry                                      |
| OpenTelemetry integration              | Systems    | Distributed tracing across Core and AIR                                       |
| Alert rules & thresholds               | Systems    | Configurable alerts for underflow, decode failure, viewer drops               |
| EPG accuracy report                    | Scheduling | Validate EPG predictions against as-run                                       |
| System dashboard data API              | Systems    | Aggregate health across all channels                                          |
| **Playback Decision Trace**            | Core/HTTP  | Explain *why* a specific asset aired, fallback decisions, break fill outcomes |

**Playback Decision Trace**:

The trace is an **append-only persisted event model** — not computed on demand via replay.

* **Storage model**: Append-only trace events written at decision time (schedule resolution, asset selection, fallback, break fill). Events are immutable once written.
* **Not replay-based**: Trace is captured as it happens, not reconstructed after the fact. This avoids the fragility of replay logic diverging from actual runtime behavior.
* **Query model**: Read-only queries over the event log, filtered by channel, time range, or aired segment.

Trace capabilities:

* Trace scheduling → execution → playout decision chain for any aired segment
* Explain why a specific asset was selected over alternatives
* Explain fallback decisions (what was attempted, why it failed, what replaced it)
* Explain break fill outcomes (which interstitials were chosen and why)

**Exit Criteria**:

* Operator can query what aired, compare it to what was scheduled, see real-time channel health, and receive alerts on anomalies
* All data available via API for UI consumption
* For any aired segment, operator can trace the decision chain from schedule to playout — no guessing
* Decision trace events are persisted (append-only), not computed retroactively

> Operators must be able to diagnose behavior without guessing.

---

### Phase E: Operator UI (Technical / Power Operator)

**Goal**: Web-based interface for technical operators — exposing system truth with clarity and correctness, not abstracting away complexity.

| Work Item                                   | Domain    | Why                                          |
| ------------------------------------------- | --------- | -------------------------------------------- |
| UI technology selection                     | Systems   | Decision needed (React/Vue/Svelte)           |
| Authentication & authorization              | Core/HTTP | Operator login, role-based access            |
| Schedule builder UI                         | UI        | Visual grid editor, validation feedback      |
| Asset library browser                       | UI        | Search, filter, eligibility indicators       |
| Channel monitoring dashboard                | UI        | Real-time status, viewer counts, health      |
| As-run & compliance viewer                  | UI        | Historical reports with filtering and export |
| Decision trace viewer                       | UI        | Visual decision chain for any aired segment  |
| EPG preview                                 | UI        | What will air in the next 24/48/72h          |
| System health overview                      | UI        | Multi-channel status, alerts, resource usage |
| Operator actions (emergency stop, override) | UI + Core | Runtime intervention from the dashboard      |

**Design Guidance**:

* 1.0 UI = **technical / power operator interface**
* Prioritize clarity and correctness over UX polish
* UI should expose system truth, not hide it
* Avoid over-investing in beginner-friendly abstractions — that is a post-1.0 concern
* All UI surfaces consume APIs built in B1/B2/C/D; no UI-only logic

**Exit Criteria**:

* A technical operator can manage the full broadcast workflow from a web browser: create schedules, manage assets, monitor channels, review reports, trace decisions, and intervene in emergencies
* UI exposes raw system state where appropriate; does not paper over complexity

---

### Phase F: Production Hardening, Recovery & 1.0 Polish

**Goal**: Stability, recovery correctness, and operational confidence for a production release — including behavior under real-world failure conditions.

| Work Item                                      | Domain  | Why                                                                |
| ---------------------------------------------- | ------- | ------------------------------------------------------------------ |
| Multi-channel stress testing                   | QA      | Verify system under realistic load (5+ concurrent channels)        |
| Graceful degradation & recovery                | Systems | Auto-recovery from transient failures (decode, network, disk)      |
| **Cold start during active broadcast**         | Systems | System must resume correct playout position from clock authority   |
| **System restart mid-playout**                 | Systems | Restart must not corrupt timeline, duplicate, or skip segments     |
| **Channel recovery validation**                | QA      | No timeline corruption, no duplicate segments, no skipped segments |
| **Reattachment to correct broadcast position** | Systems | Clock authority determines resume point; no state guessing         |
| Backup & restore procedures                    | Systems | Database backup, configuration export/import                       |
| Deployment documentation                       | Docs    | Production setup guide, upgrade procedures                         |
| Operator runbook                               | Docs    | Troubleshooting guide, common scenarios                            |
| Performance profiling & optimization           | Systems | Memory, CPU, latency budgets per channel                           |
| Security audit                                 | Systems | API auth, input validation, path traversal, injection              |
| Configuration validation                       | Systems | Startup checks, config schema enforcement                          |
| Log rotation & retention                       | Systems | Production log management                                          |

**Success Metrics (Quantified)**:

The 72-hour stability run must meet these specific thresholds:

| Metric                         | Target                           | Failure Condition                         |
| ------------------------------ | -------------------------------- | ----------------------------------------- |
| CPU per channel (steady state) | ≤ 1 core equivalent              | Sustained > 1.5 cores for > 60s           |
| Memory per channel             | ≤ 512 MB resident                | RSS exceeds 768 MB at any point           |
| Segment generation latency     | ≤ 200ms p99                      | p99 exceeds 500ms in any 10-minute window |
| Segment gap rate               | 0 gaps                           | Any gap detected                          |
| Buffer underrun rate           | 0 underruns (steady state)       | Any underrun outside of startup window    |
| Error rate (steady state)      | 0 errors                         | Any unrecoverable error                   |
| Recovery time (restart/crash)  | Correct output within 10 seconds | First valid segment > 10s after restart   |

**Exit Criteria**:

* System runs stable under multi-channel load for 72+ hours, meeting all quantified success metrics above
* Cold start and mid-playout restart produce correct, continuous output — validated by automated checks
* Channel recovery: no timeline corruption, no duplicate segments, no skipped segments
* System reattaches to correct broadcast position based on clock authority after any restart
* Operator has documentation for all common scenarios
* Security review complete
* Deployment is repeatable

> System must behave correctly under real-world failure conditions, not just ideal runtime.

---

## Dependency Graph

```
Phase A (Foundation Hardening)
    |
    v
Phase B1 (Schedule Core) ----------+
    |                               |
    v                               |
Phase B2 (Schedule Intelligence) <--+--> Phase C (Asset Management)
    |                                       |
    +---------------------------------------+
    |
    v
Phase D (Reporting, Monitoring & Decision Trace)
    |
    v
Phase E (Operator UI)
    |
    v
Phase F (Production Hardening, Recovery & 1.0)
```

* **A** must complete first — everything else builds on a clean foundation.
* **B1** must complete before B2 — automation builds on proven correctness.
* **B1** and **C** can partially overlap (asset APIs inform schedule validation).
* **B2 partially depends on C**: Virtual asset expansion and break fill pools require asset metadata from Phase C. B2 may begin after B1, but requires C capabilities for full completion.
* **D** depends on B1, B2, and C for the data it reports on.
* **E** depends on B1, B2, C, D for the APIs it consumes.
* **F** is the final pass before 1.0 tag.

---

## Out of Scope for 1.0

* **Independent Audio Servicing Pipeline** — Phase 2+ enhancement
* **Linear-to-Library QR Bridge** — Concept only; no contract or code
* **Distributed Playout Workers** — Additive evolution; single-node first
* **Deterministic Playout Test Endpoint** — QA tooling; not operator-facing
* **Continuity Announcer (AI voice)** — Requires custom iFrameEnricher
* **Waterbug/Lower-Third Overlays** — iFrameEnricher expansion
* **Diagnostic Slate Overlay** — NOC tooling; post-1.0
* **DASH support** — HLS only for 1.0
* **DRM/content protection** — Not required for personal media server use case
* **Adaptive bitrate (ABR)** — Single bitrate for 1.0
* **Full QC workflow** — Deferred from Phase C
* **Deep container hierarchies** — Deferred from Phase C
* **Extensive multi-source ingest (3+ sources)** — Deferred from Phase C
* **Complex enrichment plugin system** — Deferred from Phase C
* **Non-technical operator UX** — 1.0 targets technical/power operators only

---

## Key Decisions Needed

1. **UI framework**: React, Vue, Svelte, or something else? Affects Phase E scope.
2. **Auth model**: Simple API keys? OAuth? OIDC? Affects Phase E and production deployment.
3. **Multi-channel target for 1.0**: How many concurrent channels must be stable? (Suggested: 5-10)
4. **Alert delivery**: Email? Webhook? In-UI only? Affects Phase D scope.

---

## Guiding Principles

* **Contracts define outcomes, not implementation**: Every new capability gets an invariant before code.
* **APIs precede UI**: All Phase E work consumes APIs built in B1/B2/C/D. No UI-only logic.
* **Single authority per domain**: No new work introduces a second decision-maker for any domain.
* **No feature introduces competing decision logic**: Every addition must name its authority domain.
* **Complexity must be justified or removed**: Every addition must justify its net complexity. Prefer removal over layering.
* **Broadcast model**: RetroVue simulates real broadcast. No VOD, no rewind, no catch-up.
