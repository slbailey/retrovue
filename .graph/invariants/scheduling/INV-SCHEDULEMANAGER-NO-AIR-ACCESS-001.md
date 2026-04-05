# INV-SCHEDULEMANAGER-NO-AIR-ACCESS-001

**Domain:** scheduling

## Plain-language rule

Anything in the **planning / traffic** layer must **never** call or hold references to **AIR** (gRPC or otherwise). All engine control goes **ChannelManager → AIR** only.

## Why it exists

Prevents **two command paths** into the engine and stops **planning concepts** from leaking into AIR. Keeps `LAW-RUNTIME-AUTHORITY` and `LAW-CONTENT-AUTHORITY` intact: planning produces artifacts; execution consumes them through one mediator.

## What it constrains

- **Services:** `playlist-schedule-manager` and any future ScheduleManager/traffic implementation.
- **Not constrained:** `channel-manager`, `air-playout-engine` (their link is the allowed path).

## Failure mode if violated

Undefined switches, competing lifecycle commands, and bugs that **cannot be traced** to a single owner—plus AIR implicitly “knowing” schedule intent it must not own.
