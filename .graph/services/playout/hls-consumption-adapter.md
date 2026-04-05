# HlsConsumptionAdapter

**Domain:** playout  
**Slug:** `hls-consumption-adapter`

## Responsibility

HLS **consumption model**: phantom sessions, viewer presence, activity/expiry behavior—**without** owning channel lifecycle logic.

## Owns vs reads

- **Owns:** adapter-local consumption state (phantom tracking, presence accounting per contracts).
- **Reads:** segment ring / manifest surface via orchestrated collaborators; **must** activate through `program-director.start_channel()`.

## Upstream inputs

HTTP requests, `program-director` coordination, `session_id` correlation.

## Downstream outputs

Manifest and segment HTTP responses from in-memory stack only.

## Must NOT do

- Duplicate `start_channel()` or maintain a shadow activation registry (`INV-SINGLE-ACTIVATION-PATH-001`).
- Introduce disk-backed segment serving (`INV-HLS-NO-DISK-IO-001`).
