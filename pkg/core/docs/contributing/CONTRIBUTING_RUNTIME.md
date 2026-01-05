# Contributing to RetroVue Runtime

_Related: [Runtime: Channel manager](../runtime/channel_manager.md) • [Domain: MasterClock](../domain/MasterClock.md) • [Architecture overview](../architecture/ArchitectureOverview.md)_

This document describes the development process and architectural contracts for RetroVue's runtime components.

## Development Process

We write or update docs first.

We refine docs until roles and boundaries are explicit and unambiguous:

- who owns time (MasterClock)
- who owns schedule and broadcast day (ScheduleService)
- who plays (ChannelManager)
- who coordinates (ProgramDirector)
- who logs (AsRunLogger)
- who builds horizons (scheduler_daemon)

Only after docs are stable do we generate code.

After generating code, we generate CLI test commands whose only job is to enforce those contracts in runtime (like masterclock-\* and broadcast-day-alignment).

Breaking a contract in code (for example, using datetime.now() in ChannelManager, or cutting playback at rollover) is considered a runtime defect.

## Role Boundaries

### MasterClock

- **Owns**: Authoritative time (UTC + channel-local conversion)
- **Never**: Accepts timers, listeners, or callbacks
- **Contract**: All components must use MasterClock instead of datetime.now()

### ScheduleService

- **Owns**: Broadcast day logic, channel timing policy, horizon generation
- **Never**: Calls datetime.now() directly
- **Contract**: Only source of broadcast day classification and scheduling

### ChannelManager

- **Owns**: Content playback execution
- **Never**: Cuts content at broadcast day rollover, reschedules mid-flight
- **Contract**: Plays ScheduledSegments without interruption

### ProgramDirector

- **Owns**: Channel coordination, emergency overrides
- **Never**: Reschedules content, forces rollover cuts
- **Contract**: Coordinates without scheduling

### AsRunLogger

- **Owns**: Compliance logging, broadcast day splitting
- **Never**: Guesses broadcast day labels
- **Contract**: Uses ScheduleService.broadcast_day_for() for day classification

### scheduler_daemon (future)

- **Owns**: Horizon generation polling
- **Never**: Invents timing rules
- **Contract**: Polls MasterClock, delegates to ScheduleService

## Guide/Prevue Channel Note

There will eventually be a guide/preview / "Prevue Channel."

That UI renders a scrolling grid of "what's on now and next."

The guide always displays clean 30-minute blocks (4:00–4:30, 4:30–5:00, etc.), even if the real show starts at 4:15.

The guide will annotate late starts as Family Ties (4:15).

**Important: That formatting convention lives in the guide, not in ScheduleService. ScheduleService schedules the real world, not the pretty grid.**

We are not building this guide yet. We only document expectations so upstream components expose enough metadata when we do build it.

## Contract Enforcement

### CLI Tests

- `retrovue test masterclock-*` - Enforces MasterClock usage
- `retrovue test broadcast-day-alignment` - Enforces broadcast day logic
- `retrovue test scheduler-alignment` - Enforces scheduling contracts

### Runtime Defects

- Using datetime.now() instead of MasterClock
- Cutting playback at broadcast day rollover
- Guessing broadcast day labels instead of using ScheduleService
- Attempting to reschedule content mid-flight
- Assuming 6:00am is always a free slot

### Documentation Requirements

- All runtime components must have clear responsibility boundaries
- All integration points must be documented
- All contract violations must be testable
- All timing operations must go through MasterClock

## Development Workflow

1. **Document First**: Write or update component documentation
2. **Refine Boundaries**: Ensure clear separation of responsibilities
3. **Generate Code**: Implement based on stable documentation
4. **Create Tests**: Generate CLI tests to enforce contracts
5. **Validate**: Ensure all components follow documented boundaries

## Testing Philosophy

- CLI tests serve as contract enforcement
- Tests validate architectural boundaries, not just functionality
- Breaking a documented contract is a runtime defect
- All timing operations must be traceable to MasterClock

## Working Model

We operate "docs first."

Draft/extend docs for a subsystem.

Refine docs until roles and responsibilities are explicit (who owns time, who owns schedule, who plays, who logs, etc.).

Generate code to match the docs.

Generate CLI test commands that enforce those contracts at runtime.

Treat breaking those contracts as a runtime defect.

MasterClock is the only legal source of current time. No direct datetime.now() in runtime components.

ScheduleService is the only legal source of broadcast day, carryover handling, and per-channel timing policy.

ChannelManager does not snap at 06:00 (or whatever rollover is).

ProgramDirector coordinates but does not schedule.

AsRunLogger can split across broadcast day boundaries in reporting.

scheduler_daemon polls MasterClock; MasterClock doesn't "wake" anything.

The Prevue/guide channel will be a consumer of ScheduledSegments later, but we are intentionally NOT building that code yet. We are only documenting it so upstream systems expose the right data.

## See also

- [Runtime: Channel manager](../runtime/ChannelManager.md) - Per-channel runtime controller
- [Domain: MasterClock](../domain/MasterClock.md) - Authoritative time source
- [Runtime: Schedule service](../runtime/schedule_service.md) - Programming authority
- [Architecture overview](../architecture/ArchitectureOverview.md) - System architecture
- [Tests: Broadcast day alignment](../tests/broadcast_day_alignment.md) - Testing broadcast day logic

_Document version: v0.1 · Last updated: 2025-10-24_
