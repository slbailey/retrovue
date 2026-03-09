# INV-EPISODE-PROGRESSION-006 — Exhaustion policy correctness

Status: Invariant
Authority Level: Planning
Derived From: `LAW-CONTENT-AUTHORITY`

## Purpose

Protects `LAW-CONTENT-AUTHORITY` by ensuring that catalog exhaustion is handled predictably. An operator who sets `hold_last` expects the final episode to repeat. An operator who sets `stop` expects filler. An operator who sets `wrap` expects the series to restart.

## Guarantee

When the computed raw episode index reaches or exceeds the episode catalog size, behavior MUST follow the run's declared exhaustion policy:

- `wrap`: `raw_index % episode_count`
- `hold_last`: `min(raw_index, episode_count - 1)`
- `stop`: return FILLER when `raw_index >= episode_count`

The three policies are mutually exclusive and exhaustive.

## Preconditions

- A Progression Run exists with a declared exhaustion policy.
- The raw episode index has reached or exceeded the episode catalog size.

## Observability

An exhausted catalog produces behavior inconsistent with the declared policy (e.g., wrapping when `hold_last` is configured, or continuing when `stop` is configured).

## Deterministic Testability

Create a run with 5 episodes. Resolve day 6 (raw_index=5). Under `wrap`, assert index 0. Under `hold_last`, assert index 4. Under `stop`, assert FILLER. Resolve day 30 under each policy and verify consistent behavior.

## Failure Semantics

**Planning fault.** Incorrect exhaustion behavior means the channel airs unexpected content.

## Required Tests

- `pkg/core/tests/contracts/test_episode_progression.py`

## Enforcement Evidence

TODO
