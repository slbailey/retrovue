# INV-CUN-FEATURE-FLAG-001 — CUN Feature Flag Gate

Status: Invariant
Authority Level: Planning
Derived From: `LAW-CONTENT-AUTHORITY`, `LAW-DERIVATION`

## Purpose

Protects `LAW-CONTENT-AUTHORITY` by ensuring CUN synthesis is gated at the channel config level. Without the flag, no CUN segments are placed and no render jobs are created, guaranteeing zero overhead for channels that do not opt in.

## Guarantee

CUN synthesis MUST be gated by the channel-level `features.coming_up_next` flag. When the flag is false (or absent), no CUN segments MUST appear in the compiled schedule and no CUN render requests MUST be created.

## Preconditions

Channel config is loaded and validated.

## Observability

A CUN segment or CUN render request exists for a channel where `features.coming_up_next` is false.

## Deterministic Testability

Compile a schedule with `features.coming_up_next = false` and verify zero CUN segments in output. Repeat with the flag true and verify CUN segments appear.

## Failure Semantics

Planning fault — CUN segments placed without feature authorization.

## Required Tests

- `pkg/core/tests/contracts/test_cun_feature_flag.py`

## Enforcement Evidence

TODO
