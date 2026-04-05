# TransmissionLog

**Domain:** scheduling  
**Slug:** `transmission-log`

## What it represents

An intermediate **grid-aligned** derivation artifact between ScheduleDay-class truth and ExecutionEntry—part of the traceable chain “what was intended to transmit.”

## Lifecycle phase

**Derived**, immutable per contract family.

## Owning domain

scheduling

## What depends on it

ExecutionEntry generation and audit/traceability of execution vs editorial.

## What produces it

Scheduling derivation from ScheduleDay (and related inputs).

## What must NOT be assumed

- That it is a playout log of what **actually** aired frame-by-frame (historical as-run is separate concern).
- That runtime reads it directly instead of the **playlog / execution-window** path (playlist-shaped files are optional convenience, not the spine).
