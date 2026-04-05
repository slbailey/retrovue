# HlsSegmenter

**Domain:** playout  
**Slug:** `hls-segmenter`

## Responsibility

Generate **HLS playlists (manifests)** from in-memory segment metadata on each request—no disk reads on the hot path.

## Owns vs reads

- **Owns:** manifest generation logic and validation rules that keep playlists coherent with the ring (`INV-HLS-MANIFEST-*` family in contracts index).
- **Reads:** `segment-ring` observation/state (does not replace ring authority).

## Upstream inputs

`segment-ring`, wall-clock / sequence rules per delivery contracts.

## Downstream outputs

Manifest bytes to HTTP layer.

## Must NOT do

- Persist segments or playlists to filesystem for serving (`INV-HLS-NO-DISK-IO-001`).
- Serve ad hoc filenames outside the contracted segment naming pattern (see invariant text).
