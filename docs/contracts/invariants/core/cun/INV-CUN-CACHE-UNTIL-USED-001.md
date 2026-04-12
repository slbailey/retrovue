# INV-CUN-CACHE-UNTIL-USED-001 — Retain Rendered Assets Until Broadcast

Status: Invariant
Authority Level: Runtime
Derived From: `LAW-CONTENT-AUTHORITY`, `LAW-DERIVATION`

## Purpose

Protects `LAW-LIVENESS`. Premature deletion of a rendered CUN asset before its playout time would cause a skip at airtime.

## Guarantee

Rendered CUN assets MUST be retained until after broadcast. Cleanup MUST NOT occur before `segment_start_utc` has passed for all referencing requests.

## Preconditions

A completed CUN render exists and its segment has not yet aired.

## Observability

A rendered CUN file is deleted before its `segment_start_utc`.

## Deterministic Testability

Create a completed render with a future `segment_start_utc`. Run the cleanup cycle. Verify the file is not deleted. Advance the clock past `segment_start_utc`. Run cleanup again. Verify the file is now eligible.

## Failure Semantics

Runtime fault — CUN segment skipped at airtime due to missing file.

## Required Tests

- `server/tests/contracts/test_cun_synthesis.py`

## Enforcement Evidence

TODO
