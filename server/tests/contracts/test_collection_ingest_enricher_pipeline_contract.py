from __future__ import annotations

from retrovue.runtime.clock import SystemClock

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from retrovue.workflows.container_ingest import (
    ContainerIngestService,
    ReconciliationOutcome,
)


def test_ingest_enqueues_processor_type_not_enricher_id() -> None:
    """Configured enricher_id must resolve to processor type for queue enqueue."""
    container = SimpleNamespace(
        uuid="e0386eb8-ee8b-49b0-8d19-de71611911c5",
        name="bumpers",
        source=SimpleNamespace(type="filesystem"),
        source_id="33b1e9ea-9c89-466a-a0d6-7a38e1783b31",
        sync_enabled=True,
        ingestible=True,
        config={"enrichers": [{"enricher_id": "enricher-ffprobe-23dce623", "priority": 10}]},
    )
    enricher_row = SimpleNamespace(
        enricher_id="enricher-ffprobe-23dce623",
        type="ffprobe",
        scope="ingest",
        config={},
    )
    existing_asset = SimpleNamespace(
        uuid="036eae8d-7fe1-48c7-be75-7698ce178240",
        file_size=None,
        file_mtime=None,
    )
    locator = SimpleNamespace(
        locator="file:///mnt/data/Interstitials/bumpers/presentation/hbo/intros/1982/City Intro (1982).mp4",
        fingerprint=SimpleNamespace(size=12345, mtime=1700000000.0),
    )
    importer = SimpleNamespace(name="filesystem", validate_ingestible=lambda _c: True)

    db = MagicMock()
    enricher_q = MagicMock()
    enricher_q.filter.return_value.first.return_value = enricher_row
    db.query.return_value = enricher_q

    captured: dict[str, list[str]] = {}

    def _capture_enqueue(_asset_ids, processor_ids, *, db):
        captured["processor_ids"] = list(processor_ids)

    with (
        patch("retrovue.workflows.container_ingest.ENRICHERS", {"ffprobe": lambda **_: object()}),
        patch("retrovue.workflows.container_ingest.discover_locators", return_value=[]),
        patch("retrovue.workflows.container_ingest.load_catalog_state_for_container", return_value=[]),
        patch(
            "retrovue.workflows.container_ingest.determine_reconciliation_outcomes",
            return_value=[(locator, ReconciliationOutcome.update, existing_asset)],
        ),
        patch("retrovue.workflows.path_mapping.resolve_effective_mappings", return_value=[]),
        patch("retrovue.workflows.path_validation.validate_paths_at_import", return_value=[]),
        patch("retrovue.workflows.container_ingest.enqueue_processor_jobs", side_effect=_capture_enqueue),
    ):
        result = ContainerIngestService(db, clock=SystemClock()).ingest_container(container=container, importer=importer)

    assert result.stats.assets_updated == 1
    assert "ffprobe" in captured["processor_ids"]
    assert "enricher-ffprobe-23dce623" not in captured["processor_ids"]
