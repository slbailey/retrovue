# Ingest Orchestrator Rebuild - Completion Report

## Summary

Successfully rebuilt the Retrovue ingest orchestrator to wire together existing pipeline components.

## What Was Built

### 1. FFprobe Enricher - Chapter Extraction
- Added chapter timestamp extraction to _metadata_to_probed()
- Extracts start_ms, end_ms, and title from ffprobe JSON
- Handles missing tags gracefully

### 2. Ingest Orchestrator Module
- New module: pkg/core/src/retrovue/usecases/ingest_orchestrator.py
- Function: ingest_collection_assets(db, collection)
- Processes assets in "new" state through enrichment pipeline
- Updates asset fields and creates chapter markers
- Transitions assets to "ready" state

### 3. CLI Command Integration
- Updated source_ingest() in pkg/core/src/retrovue/cli/commands/source.py
- Calls orchestrator for each ingestible collection
- Displays progress and aggregated results
- Supports --dry-run and --json flags

### 4. Comprehensive Tests
- FFprobe chapter extraction tests (4 tests)
- Orchestrator workflow tests (5 tests)
- All tests passing

## Test Results

```
tests/adapters/enrichers/test_ffprobe_enricher_metadata.py ....
tests/usecases/test_ingest_orchestrator.py .....
9 passed in 0.18s
```

## Usage

```bash
# Run ingest for a source
retrovue source ingest "My Plex Server"

# Dry run
retrovue source ingest "My Plex Server" --dry-run

# JSON output
retrovue source ingest "My Plex Server" --json
```

## Files Modified

- pkg/core/src/retrovue/adapters/enrichers/ffprobe_enricher.py
- pkg/core/src/retrovue/cli/commands/source.py
- pkg/core/tests/adapters/enrichers/test_ffprobe_enricher_metadata.py

## Files Created

- pkg/core/src/retrovue/usecases/ingest_orchestrator.py
- pkg/core/tests/usecases/test_ingest_orchestrator.py

## Verification

All functionality has been tested and verified working.
