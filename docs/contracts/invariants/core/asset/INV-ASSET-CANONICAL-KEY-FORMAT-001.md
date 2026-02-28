# INV-ASSET-CANONICAL-KEY-FORMAT-001 — Canonical key hash is valid SHA-256 hex

Status: Invariant
Authority Level: Planning
Derived From: —

## Purpose

The `canonical_key_hash` uniquely identifies an asset within its collection. It MUST be a SHA-256 hex digest to guarantee collision resistance and consistent format for deduplication queries. Malformed hashes break uniqueness assumptions and import deduplication.

## Guarantee

`canonical_key_hash` MUST be exactly 64 lowercase hexadecimal characters (a valid SHA-256 digest). Values of incorrect length or containing non-hex characters MUST be rejected.

## Preconditions

None. This invariant holds unconditionally.

## Observability

Enforced at the database layer via CHECK constraints `chk_canon_hash_len` (length = 64) and `chk_canon_hash_hex` (regex `^[0-9a-f]{64}$`). Any INSERT or UPDATE violating these constraints MUST raise a constraint-violation error with tag `INV-ASSET-CANONICAL-KEY-FORMAT-001-VIOLATED`.

## Deterministic Testability

Construct asset stubs with valid 64-char hex hashes, short hashes, long hashes, and hashes containing non-hex characters. Assert only the valid format passes. No real database required.

## Failure Semantics

**Data integrity fault.** The import pipeline produced a malformed canonical key hash. This indicates a bug in the hash computation or a bypass of the canonical key generation path.

## Required Tests

- `pkg/core/tests/contracts/test_asset_invariants.py::TestInvAssetCanonicalKeyFormat001`

## Enforcement Evidence

- `pkg/core/src/retrovue/domain/entities.py` — CHECK constraint `chk_canon_hash_len`: `char_length(canonical_key_hash) = 64`
- `pkg/core/src/retrovue/domain/entities.py` — CHECK constraint `chk_canon_hash_hex`: `canonical_key_hash ~ '^[0-9a-f]{64}$'`
- Error tag: `INV-ASSET-CANONICAL-KEY-FORMAT-001-VIOLATED`
