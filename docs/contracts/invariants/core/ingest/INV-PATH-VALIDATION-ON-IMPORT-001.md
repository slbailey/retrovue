# INV-PATH-VALIDATION-ON-IMPORT-001 — Path mapping validated at container import, not source registration

Status: Invariant
Authority Level: Planning
Derived From: `LAW-CONTENT-AUTHORITY`, `LAW-DERIVATION`

## Purpose

Protects `LAW-CONTENT-AUTHORITY` by separating path mapping declaration (source-add time) from enforcement (container import time). Without this separation, source registration would fail for operators who only intend to import a subset of containers, or who have not yet set up storage mounts.

## Guarantee

Path mappings are stored but NOT validated for file access at source registration time. When a container is imported, the system MUST validate that at least one asset path resolves correctly using the source's path mappings before proceeding with ingest. If path resolution fails for ALL sampled assets, the container import MUST fail with a diagnostic naming the unresolvable prefix and suggesting the corrective CLI command.

## Preconditions

- The source exists with zero or more path mappings.
- The container import is initiated (manually or via auto-sync).
- The container has at least one discoverable asset for sampling.

## Observability

- Container import failure emits a structured log event with `path_validation_failed`, the source id, container id, and the unresolvable prefix.
- Partial resolution (some samples fail, some pass) emits a structured warning with the failing sample paths.

## Deterministic Testability

1. Create a source with no path mappings. Import a container. Assert import fails with a diagnostic message naming the missing mapping.
2. Create a source with a valid path mapping. Import a container whose assets fall within the mapping prefix. Assert import succeeds.
3. Create a source with a mapping that does not cover the container's asset paths. Assert import fails with a diagnostic.
4. Create a source with a mapping that covers some but not all sampled assets. Assert import proceeds with a warning.
5. Assert that `retrovue source add` with invalid path mappings does NOT fail at source registration time.

## Failure Semantics

**Planning fault.** An imported container with unresolvable paths produces assets that cannot be located at playout time. The fault lies in the import pipeline that did not enforce path validation.

## Required Tests

- `pkg/core/tests/contracts/ingest/test_inv_path_validation_on_import.py`

## Enforcement Evidence

TODO
