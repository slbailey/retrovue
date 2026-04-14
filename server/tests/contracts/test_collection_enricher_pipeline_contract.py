from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from retrovue.usecases.collection_enrichers import apply_enrichers_to_collection


def test_apply_enrichers_uses_processor_type_for_pipeline_ids():
    """Configured enricher_id must resolve to processor type (ffprobe) for queueing."""
    container = SimpleNamespace(
        uuid="c58da5dc-ad1f-41db-9116-2ad144c489e5",
        name="commercials",
        config={"enrichers": [{"enricher_id": "enricher-ffprobe-23dce623", "priority": 10}]},
    )
    enricher_row = SimpleNamespace(
        enricher_id="enricher-ffprobe-23dce623",
        type="ffprobe",
        scope="ingest",
        config={},
    )
    asset = SimpleNamespace(
        uuid="0fc8a7a1-236e-4ab3-bf4f-342c1b64241d",
        canonical_uri="file:///tmp/a.mp4",
        uri="file:///tmp/a.mp4",
        state="new",
        is_deleted=False,
        last_enricher_checksum=None,
    )

    db = MagicMock()
    container_q = MagicMock()
    enricher_q = MagicMock()
    asset_q = MagicMock()

    # _resolve_collection UUID path
    container_q.filter.return_value.first.return_value = container
    container_q.filter.return_value.all.return_value = [container]
    enricher_q.filter.return_value.first.return_value = enricher_row
    asset_q.filter.return_value.filter.return_value.all.return_value = [asset]

    def _query_side_effect(model):
        name = getattr(model, "__name__", "")
        if name == "Container":
            return container_q
        if name == "Enricher":
            return enricher_q
        if name == "Asset":
            return asset_q
        return MagicMock()

    db.query.side_effect = _query_side_effect

    captured = {}

    def _fake_enrich_asset(_db, _asset, pipeline, *, pipeline_checksum=None):
        captured["pipeline_ids"] = [pid for (_pr, pid, _inst) in pipeline]
        return SimpleNamespace(new_state="enriching", enricher_errors=[])

    with patch("retrovue.usecases.collection_enrichers.enrich_asset", side_effect=_fake_enrich_asset):
        result = apply_enrichers_to_collection(
            db,
            collection_selector=str(container.uuid),
        )

    assert result["stats"]["assets_considered"] == 1
    assert "ffprobe" in captured["pipeline_ids"]
    assert "enricher-ffprobe-23dce623" not in captured["pipeline_ids"]
