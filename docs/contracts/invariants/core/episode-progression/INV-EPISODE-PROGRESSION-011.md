# INV-EPISODE-PROGRESSION-011 — Anchor validity

Status: Invariant
Authority Level: Planning
Derived From: `LAW-CONTENT-AUTHORITY`

## Purpose

Protects `LAW-CONTENT-AUTHORITY` by ensuring that the progression anchor is a valid occurrence. An anchor on a non-matching day makes the occurrence count undefined.

## Guarantee

The anchor date's day-of-week MUST have its bit set in the run's `placement_days` bitmask.

    (1 << anchor_date.weekday()) & placement_days != 0

An anchor on a non-matching day is a validation fault.

## Preconditions

- A Progression Run is being created or updated.

## Observability

A Progression Run exists with an anchor date whose day-of-week bit is not set in its `placement_days` bitmask.

## Deterministic Testability

Attempt to create a run with anchor on Saturday (weekday=5) and `placement_days=31` (weekdays only). Assert validation fault. Create a run with anchor on Monday and `placement_days=31`. Assert success.

## Failure Semantics

**Validation fault** at run creation or update time. The system MUST reject the run record before it is persisted.

## Required Tests

- `pkg/core/tests/contracts/test_episode_progression.py`

## Enforcement Evidence

TODO
