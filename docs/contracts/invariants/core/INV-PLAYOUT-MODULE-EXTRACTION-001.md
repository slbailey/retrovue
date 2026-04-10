# INV-PLAYOUT-MODULE-EXTRACTION-001

## Behavioral Guarantee

Helper classes extracted from `program_director.py` and `channel_manager.py` MUST be importable from their dedicated sibling modules. Original import paths MUST continue to work via re-exports.

## Authority Model

Module structure under `retrovue/runtime/` owns this guarantee.

## Boundary / Constraint

The following classes MUST be importable from their dedicated modules:

- `retrovue.runtime.pd_helpers`: `_RawTSResponse`, `HLSAccessFilter`, `SystemMode`, `HlsDiagnosticsState`, `ChannelManagerProvider`
- `retrovue.runtime.cm_helpers`: `_FeedState`, `_AsRunAnnotation`, `TracedSocket`
- `retrovue.runtime.block_plan_producer`: `BlockPlanProducer`

Backward-compatible re-exports from `program_director` and `channel_manager` MUST remain functional.

## Violation

Any import of the above classes from either the new dedicated module or the original module that raises `ImportError` constitutes a violation.

## Required Tests

- `pkg/core/tests/contracts/runtime/test_inv_playout_module_extraction.py`

## Enforcement Evidence
TODO
