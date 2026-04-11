# AsRunTimelineContract_v0.1

**Classification:** Contract (AIR Coordination)
**Owner:** `AsRunWriter` (REMOVED)
**Status:** RETIRED

---

## RETIRED

This contract has been retired. AIR does not produce `.asrun` artifacts.

**Reason:** Core is the sole as-run authority. AIR emits execution evidence via EvidenceEmitter + EvidenceSpool + GrpcEvidenceClient. Core persists official `.asrun` artifacts from evidence data.

**Replaced by:**

- [AirExecutionEvidenceEmitterContract_v0.1.md](AirExecutionEvidenceEmitterContract_v0.1.md) — AIR-side evidence emission
- [AirExecutionEvidenceSpoolContract_v0.1.md](AirExecutionEvidenceSpoolContract_v0.1.md) — Durable spool until Core ACK

All INV-ASRUN-TIMELINE-001 through INV-ASRUN-TIMELINE-007 invariants are retired.
