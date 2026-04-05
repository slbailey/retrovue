# INV-SINGLE-ACTIVATION-PATH-001

**Domain:** playout

## Plain-language rule

There is **exactly one** way to activate a channel for consumption: **`ProgramDirector.start_channel()`** (conceptually). HLS and TS adapters add viewer behavior but **must not** invent their own activation or registry.

## Why it exists

Stops duplicate lifecycle state (phantom “active” channels, double AIR starts, divergent teardown). Aligns with consumption-adapter model: adapters wrap PD-owned lifecycle.

## What it constrains

- **Services:** `hls-consumption-adapter`, `ts-consumption-adapter`, any future delivery adapter.
- **Implied:** `program-director` owns the activation entry point.

## Failure mode if violated

Resource leaks, ghost playout, inconsistent viewer counts, and incidents where logs **cannot** be correlated to a single activation path.
