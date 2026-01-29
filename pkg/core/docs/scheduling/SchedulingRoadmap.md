_Related: [Scheduling system architecture](SchedulingSystem.md) • [Domain: Scheduling](../domain/Scheduling.md) • [Developer roadmap](../developer/development-roadmap.md)_

# Scheduling system implementation roadmap

## Purpose

This roadmap breaks down the implementation of the scheduling system architecture into manageable phases. Each phase builds on the previous one, ensuring a solid foundation before adding complexity.

## Current state

The scheduling system architecture is documented, but implementation is in early stages. The domain models exist (Channel, SchedulePlan, SchedulePlanBlockAssignment, BroadcastScheduleDay, BroadcastPlaylogEvent), but the runtime services that orchestrate these layers are not yet fully implemented.

## Implementation phases

### Phase 1: SchedulePlan and schedule foundation

**Goal**: Establish the basic plan-to-schedule flow.

**Components**:

- SchedulePlan creation and management
- Zone and SchedulableAsset definition within plans
- Grid block configuration
- ScheduleDay generation from plans
- Basic content selection rules (placeholder or fixed content)

**Deliverables**:

- CLI commands for SchedulePlan CRUD operations
- CLI commands for schedule day creation
- Contract tests for plan and schedule operations
- Database schema validation for plan/schedule relationships

**Success criteria**:

- Operators can create a SchedulePlan with Zones and Patterns
- Operators can generate a ScheduleDay from a plan for a specific date
- Schedule data is persisted correctly in the database

**Estimated effort**: 2-3 days

---

### Phase 2: EPG generation

**Goal**: Generate Electronic Program Guide from schedule state.

**Components**:

- EPG generation service that reads schedule and playlog events
- EPG view generation (coarse program-level information)
- Plan horizon extension (2-3 days ahead)
- EPG export format (XMLTV or similar)

**Deliverables**:

- EPG generation logic
- CLI command to view/generate EPG
- Contract tests for EPG generation
- EPG displays correctly in test scenarios

**Success criteria**:

- EPG shows program-level schedule for a channel
- EPG extends 2-3 days ahead
- EPG reflects schedule state accurately

**Estimated effort**: 2-3 days

**Dependencies**: Phase 1 (schedule foundation)

---

### Phase 3: Playlog generation (rolling horizon)

**Goal**: Generate fine-grained playout plans with specific assets.

**Components**:

- Playlog generation service
- Rolling horizon logic (3-4 hours ahead)
- Asset selection from schedule rules
- Ad break insertion logic (basic)
- Bumper and interstitial insertion
- Master clock integration for timing

**Deliverables**:

- Playlog generation service
- Rolling horizon maintenance
- CLI command to view/generate playlog
- Contract tests for playlog generation
- Playlog events created with correct timestamps

**Success criteria**:

- Playlog generates 3-4 hours ahead of current time
- Playlog contains specific asset references
- Playlog includes ad breaks and bumpers
- Playlog timestamps align with master clock
- Only assets with `state='ready'` and `approved_for_broadcast=true` are included

**Estimated effort**: 4-5 days

**Dependencies**: Phase 1 (schedule foundation), MasterClock implementation

---

### Phase 4: Viewer join and synchronization

**Goal**: Handle viewer joins with proper synchronization.

**Components**:

- Viewer join detection in ChannelManager
- Grid block start calculation
- Time offset calculation for mid-program joins
- Playback alignment to master clock
- Sync checkpoint logic (if needed for performance)

**Deliverables**:

- ChannelManager viewer join logic
- Master clock offset calculation
- Synchronized playback for all viewers
- Contract tests for join behavior

**Success criteria**:

- Viewers joining mid-program see correct offset
- All viewers see synchronized playback
- Join time aligns with master clock
- No drift between viewers

**Estimated effort**: 2-3 days

**Dependencies**: Phase 3 (playlog generation), ChannelManager foundation

---

### Phase 5: As-run logging

**Goal**: Record what actually aired.

**Components**:

- As-run log service
- Event recording on asset start
- Master clock timestamp capture
- Log storage and retrieval
- Fallback condition logging

**Deliverables**:

- AsRunLogger implementation
- Log storage mechanism
- CLI command to view as-run logs
- Contract tests for logging

**Success criteria**:

- Every asset start is logged with timestamp
- Logs include channel, asset, and timing information
- Logs can be queried for historical data
- Logging failures don't block playout

**Estimated effort**: 2-3 days

**Dependencies**: Phase 4 (viewer join), ChannelManager playout execution

---

### Phase 6: Content selection rules

**Goal**: Implement smart content selection from schedule rules.

**Components**:

- Content selection engine
- Series episode selection
- Movie selection
- Content rotation rules
- Conflict resolution
- Underfill handling

**Deliverables**:

- Content selection service
- Rule evaluation logic
- CLI commands for rule testing
- Contract tests for selection

**Success criteria**:

- Rules resolve to specific assets correctly
- Rotation prevents too-frequent repeats
- Conflicts are resolved appropriately
- Underfill cases are handled gracefully

**Estimated effort**: 3-4 days

**Dependencies**: Phase 3 (playlog generation), Asset catalog with sufficient content

---

### Phase 7: Advanced scheduling features

**Goal**: Add preemption, rebalancing, and dynamic updates.

**Components**:

- Preemption logic (breaking news scenarios)
- Dynamic playlog updates
- Content rebalancing mid-day
- EPG updates for schedule changes

**Deliverables**:

- Preemption service
- Dynamic update logic
- CLI commands for manual preemption
- Contract tests for preemption

**Success criteria**:

- Preemption updates playlog correctly
- EPG reflects changes
- All viewers see updated content
- Changes are logged in as-run log

**Estimated effort**: 3-4 days

**Dependencies**: Phase 6 (content selection), Phase 5 (as-run logging)

---

## Proof of concept strategy

Before implementing all phases, validate the system with a minimal proof of concept:

### POC setup

1. **Single SchedulePlan**: Create one plan with basic Zones and Patterns
2. **Fixed content**: Populate Patterns with fixed series (e.g., "Cheers", "Big Bang Theory")
3. **Daily schedule**: Generate ScheduleDays from plan for multiple days
4. **Basic playlog**: Build runtime playlog for fixed content
5. **Simple EPG**: Generate EPG from schedule

### POC validation

- SchedulePlans generate ScheduleDays correctly
- Playlog generates with correct timing
- EPG shows program information
- Viewer joins work with synchronization
- As-run log captures events

### POC success criteria

- End-to-end flow works: SchedulePlan → ScheduleDay → EPG → Playlog → Playout
- Master clock synchronization works
- Viewer join behavior is correct
- System is ready for content selection rules

**Estimated effort for POC**: 1-2 days (using phases 1-4 basics)

---

## Dependencies and prerequisites

### Required infrastructure

- **MasterClock**: Must be implemented and tested before Phase 3
- **ChannelManager**: Must have basic playout capability before Phase 4
- **Asset catalog**: Must have assets in `ready` state for Phase 3+
- **Database schema**: All scheduling domain models must be in place

### External dependencies

- **Contract tests**: Each phase should have contract tests before moving to next phase
- **CLI commands**: Operator interface for each major component
- **Documentation**: Update architecture docs as implementation progresses

---

## Risk mitigation

### High-risk areas

1. **Master clock synchronization**: Critical for all timing-dependent features

   - **Mitigation**: Implement and test MasterClock thoroughly before Phase 3
   - **Validation**: Test timezone handling, DST transitions, monotonicity

2. **Rolling horizon complexity**: Complex state management

   - **Mitigation**: Start with simple fixed-horizon, add rolling logic incrementally
   - **Validation**: Test horizon extension under various conditions

3. **Content selection rules**: Complex logic with many edge cases

   - **Mitigation**: Start with simple rules, add complexity gradually
   - **Validation**: Comprehensive contract tests for rule evaluation

4. **Viewer synchronization**: Potential for drift or desync
   - **Mitigation**: Strict master clock alignment, test with multiple concurrent viewers
   - **Validation**: Load testing with multiple viewers joining at different times

---

## Success metrics

### Phase completion criteria

- All contract tests pass
- CLI commands work as specified
- Documentation is updated
- No critical bugs or race conditions
- Performance is acceptable for expected load

### System-wide criteria

- Template → Schedule → EPG → Playlog → Playout flow works end-to-end
- Master clock synchronization is accurate
- Viewer join behavior is correct
- As-run logging captures all events
- System handles failures gracefully

---

## Next steps

### Immediate priorities

1. **Complete Phase 1**: Template and schedule foundation

   - This is the foundation for everything else
   - Establishes the data model and basic operations

2. **Validate POC**: Run proof of concept with fixed content

   - Validates the architecture before adding complexity
   - Identifies any architectural issues early

3. **Implement MasterClock**: If not already complete
   - Required for Phase 3+
   - Critical for all timing operations

### Recommended sequence

1. Phase 1 (SchedulePlan/Schedule foundation)
2. POC validation (end-to-end with fixed content)
3. Phase 3 (Playlog generation) - depends on MasterClock
4. Phase 2 (EPG generation) - can run in parallel with Phase 3
5. Phase 4 (Viewer join) - depends on Phase 3
6. Phase 5 (As-run logging) - depends on Phase 4
7. Phase 6 (Content selection) - can enhance Phase 3
8. Phase 7 (Advanced features) - depends on all previous phases

---

## See also

- [Scheduling system architecture](SchedulingSystem.md) - Detailed architecture documentation
- [Domain: Scheduling](../domain/Scheduling.md) - Domain model documentation
- [Developer roadmap](../developer/development-roadmap.md) - Overall project roadmap
- [Runtime: ScheduleService](../runtime/schedule_service.md) - Schedule service implementation
- [Domain: MasterClock](../domain/MasterClock.md) - Master clock implementation
