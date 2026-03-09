# INV-EPISODE-PROGRESSION-004 — Placement isolation

Status: Invariant
Authority Level: Planning
Derived From: `LAW-CONTENT-AUTHORITY`, `LAW-DERIVATION`

## Purpose

Protects `LAW-CONTENT-AUTHORITY` by ensuring that independent program placements do not corrupt each other's progression. Two strips airing at different times or on different day patterns are separate editorial decisions with separate episode sequences.

## Guarantee

Two Progression Runs with different run identities MUST NOT influence each other. Episode selection for one run MUST NOT read or modify state belonging to another run.

## Preconditions

- Two or more Progression Runs exist on the same channel with different run identities.

## Observability

Compiling or resolving one run alters the episode selected by a different run on the same or different channel.

## Deterministic Testability

Create two runs on the same channel: Bonanza at 10:00 (run_id "bonanza_am") and Bonanza at 23:00 (run_id "bonanza_pm") with different anchor episodes. Resolve both for the same broadcast day. Assert each selects its own expected episode. Resolve run A for 5 consecutive days. Assert run B's episode for any day is unchanged.

## Failure Semantics

**Planning fault.** Shared state between independent runs means schedule edits to one strip can corrupt another.

## Required Tests

- `pkg/core/tests/contracts/test_episode_progression.py`

## Enforcement Evidence

TODO
