# SegmentRing

**Domain:** playout  
**Slug:** `segment-ring`

## What it represents

The **bounded in-memory sliding window** of completed HLS segments and metadata for a channel—**authority** for which segments exist for manifest and serve paths.

## Lifecycle phase

**Runtime** mutable structure (eviction, push rules per contracts).

## Owning domain

playout

## What depends on it

`hls-segmenter` (manifest generation), HTTP segment handlers, staleness/recovery logic.

## What produces it

Segment completion path from live playout/HLS pipeline (feeds the ring).

## What must NOT be assumed

- That segments live on disk for delivery (forbidden by `INV-HLS-NO-DISK-IO-001`).
- That any second parallel HLS cache may exist (single-stack invariant family).
