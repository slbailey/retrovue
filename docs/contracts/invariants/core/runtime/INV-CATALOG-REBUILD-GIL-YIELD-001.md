# INV-CATALOG-REBUILD-GIL-YIELD-001

## Behavioral Guarantee

`CatalogAssetResolver._load()` MUST periodically yield the GIL during the asset-processing loop so that the upstream reader thread is not starved during concurrent catalog rebuilds.

## Authority Model

CatalogAssetResolver owns catalog construction. GIL scheduling between the resolver rebuild and the upstream reader thread is the resolver's responsibility.

## Boundary / Constraint

1. `_load()` MUST call `time.sleep(>=0.010)` periodically inside the asset-processing loop. The yield duration MUST be at least 10ms (a 1ms yield is insufficient to prevent upstream reader starvation).
2. The yield MUST be conditional — executed only at batch boundaries, not on every iteration.
3. The yield MUST execute multiple times during a large rebuild (12k+ assets) so that no single GIL-held stretch exceeds the upstream reader's select timeout (50ms).

## Violation

Absence of `time.sleep()` inside `_load()` asset-processing loop; yield duration below 10ms; unconditional per-iteration yield; UPSTREAM_LOOP `select_ms` spikes >150ms during concurrent catalog rebuild and active streaming.

## Required Tests

- `pkg/core/tests/contracts/runtime/test_inv_catalog_rebuild_gil_yield.py`

## Enforcement Evidence

TODO
