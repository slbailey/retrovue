# Zone

**Domain:** scheduling  
**Slug:** `zone`

## What it represents

A **time-bounded scheduling region** within the grid that holds schedulable content or avails, without cutting in-flight longform against contract rules.

## Lifecycle phase

**Planned** as part of editorial scheduling structures; materializes in resolved daily views.

## Owning domain

scheduling

## What depends on it

Program placement, break/traffic structures, and resolution into ScheduleDay.

## What produces it

Editorial scheduling (SchedulePlan-level intent and tooling).

## What must NOT be assumed

- That zones are visible runtime objects for AIR.
- That they auto-extend or mid-cut programs contrary to grid/longform invariants.
