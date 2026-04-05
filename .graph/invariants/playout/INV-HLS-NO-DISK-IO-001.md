# INV-HLS-NO-DISK-IO-001

**Domain:** playout

## Plain-language rule

HLS **segments and playlists** for delivery are **in-memory only** on serve/produce hot paths—no reading/writing segment files for the live stack.

## Why it exists

Single delivery stack (`segment-ring` + `hls-segmenter`), predictable liveness, no hidden I/O latency or double-cache behavior.

## What it constrains

- **Services:** `hls-segmenter`, HLS HTTP handlers owned by playout orchestration, segment push path into `segment-ring`.
- **Entity:** `segment-ring` as the segment store of record for HLS.

## Failure mode if violated

Stalls, desync between disk and memory, security/ops surprises from temp paths, and **parallel unofficial** HLS stacks.
