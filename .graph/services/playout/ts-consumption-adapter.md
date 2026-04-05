# TsConsumptionAdapter

**Domain:** playout  
**Slug:** `ts-consumption-adapter`

## Responsibility

Raw **MPEG-TS** consumption path: fanout/wiring for TS clients while respecting the same **single activation** rule as HLS.

## Owns vs reads

- **Owns:** TS fanout adapter concerns only.
- **Reads:** stream from channel playout path once active.

## Upstream inputs

HTTP TS clients, `program-director` / `channel-manager` active session.

## Downstream outputs

Chunked TS bytes to clients.

## Must NOT do

- Activate channels without routing through `start_channel()` (`INV-SINGLE-ACTIVATION-PATH-001`).
- Perform scheduling or asset resolution.
