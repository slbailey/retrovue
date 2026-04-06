# EvidenceServer

**Domain:** playout  
**Slug:** `evidence-server`

## Responsibility

Core-side gRPC server that receives execution evidence from AIR via bidirectional streaming (`ExecutionEvidenceService.EvidenceStream`). Handles handshake, deduplication, durable write to as-run artifacts, and ACK emission.

## Owns vs reads

- **Owns:** durable ACK store per (channel_id, playout_session_id); as-run write path (`.asrun` + `.asrun.jsonl`).
- **Reads:** clock from `master-clock` (injected via RETA-11); evidence messages from AIR.

## Upstream inputs

AIR evidence stream (gRPC bidirectional). Clock authority from `master-clock`.

## Downstream outputs

ACK messages back to AIR. Persistent as-run artifacts on disk.

## Must NOT do

- Emit or invent execution evidence (AIR has emission authority).
- ACK before durable write is flushed (write-then-ACK ordering per GrpcEvidenceInterfaceContract).
- Bypass `master-clock` for timestamp generation.
