# INV-CHANNELMANAGER-NO-PLANNING-001

**Domain:** playout

## Plain-language rule

While a channel is in **active playout**, `channel-manager` must **not** do scheduling work: no asset-library queries for playback, no building or extending **playlog**, **execution entries**, or **playlist-shaped** interchange as a substitute for that spine, no schedule math, no “fix the plan from EPG,” no on-demand playlog extension.

## Why it exists

Forces planning failures to surface as **planning faults** instead of silent runtime improvisation. Protects `LAW-RUNTIME-AUTHORITY` (execution window is input) and `LAW-CONTENT-AUTHORITY` (editorial intent stays in planning).

## What it constrains

- **Service:** `channel-manager` (and anything in its runtime call stack acting on its behalf).

## Failure mode if violated

Non-reproducible playout, hidden horizon bugs, and **unattributable** divergence between what was scheduled and what aired.
