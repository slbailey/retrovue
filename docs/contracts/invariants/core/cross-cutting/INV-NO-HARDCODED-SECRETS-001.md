# INV-NO-HARDCODED-SECRETS-001 — No secret material in git-tracked source files

Status: Invariant
Authority Level: Cross-layer
Derived From: `LAW-LIVENESS`, `LAW-CONTENT-AUTHORITY`

## Purpose

Secret material (API keys, authentication tokens, passwords, connection strings with embedded credentials) committed to git-tracked source files creates an irreversible exposure vector. A single push to a shared or public remote compromises every credential in the repository history. Leaked database credentials threaten `LAW-LIVENESS` (system cannot operate if credentials are rotated after breach). Leaked Plex tokens threaten `LAW-CONTENT-AUTHORITY` (unauthorized access to content sources).

## Guarantee

No git-tracked file MUST contain literal secret material. All secrets MUST be loaded at runtime from environment variables or from files excluded by `.gitignore`.

## Preconditions

- The repository has a `.gitignore` that excludes secret-bearing files (`secrets.env`, `.env`, credential JSON files).

## Observability

A static scan of all git-tracked files against known secret patterns (API key prefixes, `password=`, `token=` with literal values, connection strings with embedded passwords) detects violations. The scan MUST run against `git ls-files` output, not the working tree, to ensure only tracked files are checked.

## Deterministic Testability

Enumerate all git-tracked files matching source extensions (`.py`, `.yaml`, `.yml`, `.json`, `.sh`, `.toml`, `.cfg`, `.ini`). Apply regex patterns for known secret formats. Assert zero matches. No real-time waits required.

## Failure Semantics

**Operator fault** — a developer committed secret material that should have been externalized. Remediation: rotate the exposed credential, remove from source, add to a gitignored secrets file.

## Required Tests

- `pkg/core/tests/contracts/test_inv_no_hardcoded_secrets.py`

## Enforcement Evidence

TODO
