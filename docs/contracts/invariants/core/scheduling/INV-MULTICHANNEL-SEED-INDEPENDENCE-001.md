# INV-MULTICHANNEL-SEED-INDEPENDENCE-001 — Per-channel seed independence

Status: Invariant
Authority Level: Planning
Derived From: `LAW-CONTENT-AUTHORITY`, `LAW-DERIVATION`

## Purpose

Protects `LAW-CONTENT-AUTHORITY` by ensuring each channel's compilation seed is derived from its own channel_id. Shared or colliding seeds cause channels to air identical content simultaneously, violating editorial independence.

## Guarantee

Compilation seeds MUST incorporate the channel_id such that different channel_ids produce different seeds for the same broadcast_day. Same (channel_id, broadcast_day) MUST produce identical seeds across invocations.

## Preconditions

Two or more channels exist with distinct channel_ids.

## Observability

Compiling the same SchedulePlan DSL for two different channel_ids on the same broadcast_day MUST produce different asset selections.

## Deterministic Testability

Call `compilation_seed(channel_a, day)` and `compilation_seed(channel_b, day)` where `channel_a != channel_b`. Assert seeds differ. Compile full schedules for both and assert program_blocks differ.

## Failure Semantics

**Planning fault.** Seed collision causes channels to air identical movie selections, destroying editorial variety.

## Required Tests

- `server/tests/contracts/scheduling/test_vertical_slice_derivation_chain.py`
- `server/tests/contracts/scheduling/test_multichannel_isolation.py`

## Enforcement Evidence

TODO
