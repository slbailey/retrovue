"""
Contract: docs/contracts/resources/CollectionIngestContract.md
Rules covered:
- B-20: ingest builds handler payload
- B-21: ingest calls handler before persisting asset
- B-22: ingest persists handler output to per-domain tables
- B-24: --dry-run runs full pipeline but rolls back
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from retrovue.adapters.importers.base import DiscoveredItem
from retrovue.cli.commands._ops.collection_ingest_service import CollectionIngestService


def _fake_collection() -> Any:
    class _C:
        uuid = uuid.UUID("00000000-0000-0000-0000-000000000001")
        name = "Test Collection"
        sync_enabled = True
        ingestible = True

    return _C()


def _fake_importer() -> Any:
    class _I:
        name = "test-importer"

        def validate_ingestible(self, collection: Any) -> bool:  # noqa: ARG002
            return True

        def discover(self) -> list[DiscoveredItem]:
            return [
                DiscoveredItem(
                    path_uri="file:///tmp/a.mkv",
                    provider_key="k",
                    raw_labels=["title:Akira"],
                )
            ]

        def resolve_local_uri(self, item: Any, *, collection: Any | None = None, path_mappings=None) -> str:  # noqa: ARG002
            return "file:///tmp/a.mkv"

    return _I()


@pytest.fixture
def service(monkeypatch: pytest.MonkeyPatch) -> CollectionIngestService:
    # MagicMock Session with add/flush
    class _DB:
        def add(self, _obj: Any) -> None:
            return None

        def flush(self) -> None:
            return None

        def scalar(self, _stmt: Any) -> Any:
            # Duplicate detection returns None in these unit tests
            return None

    # Minimize external touches
    monkeypatch.setattr("retrovue.infra.canonical.canonical_key_for", lambda *a, **k: "canon/key")
    monkeypatch.setattr("retrovue.infra.canonical.canonical_hash", lambda *a, **k: "h" * 64)
    # No enrichers during this test path
    monkeypatch.setattr("retrovue.cli.commands._ops.collection_ingest_service.ENRICHERS", {}, raising=True)
    return CollectionIngestService(_DB())


def test_editorial_triggers_persistence(service: CollectionIngestService, monkeypatch: pytest.MonkeyPatch) -> None:
    """B-20, B-21, B-22: editorial block is persisted via helper."""

    calls: dict[str, Any] = {"args": None, "kwargs": None}

    def _persist(db, asset, *, editorial=None, probed=None, station_ops=None, relationships=None, sidecar=None):  # noqa: ANN001
        calls["kwargs"] = {
            "editorial": editorial,
            "probed": probed,
            "station_ops": station_ops,
            "relationships": relationships,
            "sidecar": sidecar,
        }

    monkeypatch.setattr(
        "retrovue.cli.commands._ops.collection_ingest_service.persist_asset_metadata",
        _persist,
        raising=True,
    )

    # Handler returns editorial at top-level and resolved_fields
    monkeypatch.setattr(
        "retrovue.cli.commands._ops.collection_ingest_service.handle_ingest",
        lambda payload: {"editorial": {"title": "Akira"}, "resolved_fields": {"editorial": {"title": "Akira"}}},  # noqa: E501
        raising=True,
    )

    collection = _fake_collection()
    importer = _fake_importer()

    service.ingest_collection(collection=collection, importer=importer)

    assert calls["kwargs"] is not None
    assert calls["kwargs"]["editorial"] == {"title": "Akira"}


def test_probed_triggers_persistence(service: CollectionIngestService, monkeypatch: pytest.MonkeyPatch) -> None:
    """B-20, B-22: probed block is persisted via helper from handler resolved_fields."""

    calls: dict[str, Any] = {"kwargs": None}

    def _persist(db, asset, *, editorial=None, probed=None, station_ops=None, relationships=None, sidecar=None):  # noqa: ANN001
        calls["kwargs"] = {
            "editorial": editorial,
            "probed": probed,
            "station_ops": station_ops,
            "relationships": relationships,
            "sidecar": sidecar,
        }

    monkeypatch.setattr(
        "retrovue.cli.commands._ops.collection_ingest_service.persist_asset_metadata",
        _persist,
        raising=True,
    )

    # Handler returns probed under resolved_fields
    monkeypatch.setattr(
        "retrovue.cli.commands._ops.collection_ingest_service.handle_ingest",
        lambda payload: {"editorial": {}, "resolved_fields": {"probed": {"duration_ms": 120000}}},
        raising=True,
    )

    collection = _fake_collection()
    importer = _fake_importer()

    service.ingest_collection(collection=collection, importer=importer)

    assert calls["kwargs"] is not None
    assert calls["kwargs"]["probed"] == {"duration_ms": 120000}


def test_handler_is_called(service: CollectionIngestService, monkeypatch: pytest.MonkeyPatch) -> None:
    """B-21: handler MUST be invoked before persistence."""

    called = {"ok": False}

    def _handle(payload):  # noqa: ANN001
        called["ok"] = True
        return {"editorial": {}, "resolved_fields": {}}

    monkeypatch.setattr(
        "retrovue.cli.commands._ops.collection_ingest_service.handle_ingest",
        _handle,
        raising=True,
    )

    # No-op persistence
    monkeypatch.setattr(
        "retrovue.cli.commands._ops.collection_ingest_service.persist_asset_metadata",
        lambda *a, **k: None,  # noqa: ANN001
        raising=True,
    )

    collection = _fake_collection()
    importer = _fake_importer()

    service.ingest_collection(collection=collection, importer=importer)

    assert called["ok"] is True


def test_child_tables_have_cascade_fk() -> None:
    """B-23: Each metadata table must have FK → assets.uuid with ON DELETE CASCADE."""
    from retrovue.domain.entities import (
        AssetEditorial,
        AssetProbed,
        AssetRelationships,
        AssetSidecar,
        AssetStationOps,
    )

    for model in (AssetEditorial, AssetProbed, AssetStationOps, AssetRelationships, AssetSidecar):
        fks = list(model.__table__.foreign_keys)
        assert fks, f"{model.__name__} must define a foreign key"
        fk = fks[0]
        # target_fullname like 'assets.uuid'
        assert getattr(fk, "target_fullname", "").endswith("assets.uuid"), f"{model.__name__} FK must target assets.uuid"
        assert getattr(fk, "ondelete", None) == "CASCADE", f"{model.__name__} FK must be ON DELETE CASCADE"


def test_dry_run_does_not_persist(service: CollectionIngestService, monkeypatch: pytest.MonkeyPatch) -> None:
    """B-24: --dry-run executes but does not persist child tables."""

    called = {"persist": False}

    def _persist(*_a, **_k):  # noqa: ANN001
        called["persist"] = True

    monkeypatch.setattr(
        "retrovue.cli.commands._ops.collection_ingest_service.persist_asset_metadata",
        _persist,
        raising=True,
    )

    # Handler still returns data in dry-run
    monkeypatch.setattr(
        "retrovue.usecases.metadata_handler.handle_ingest",
        lambda payload: {"editorial": {"title": "Akira"}, "resolved_fields": {"editorial": {"title": "Akira"}}},  # noqa: E501
        raising=True,
    )

    collection = _fake_collection()
    importer = _fake_importer()

    service.ingest_collection(collection=collection, importer=importer, dry_run=True)

    assert called["persist"] is False


def test_station_ops_triggers_persistence(service: CollectionIngestService, monkeypatch: pytest.MonkeyPatch) -> None:
    """B-22: station_ops block is persisted via helper from handler resolved_fields."""

    calls: dict[str, Any] = {"kwargs": None}

    def _persist(db, asset, *, editorial=None, probed=None, station_ops=None, relationships=None, sidecar=None):  # noqa: ANN001
        calls["kwargs"] = {
            "editorial": editorial,
            "probed": probed,
            "station_ops": station_ops,
            "relationships": relationships,
            "sidecar": sidecar,
        }

    monkeypatch.setattr(
        "retrovue.cli.commands._ops.collection_ingest_service.persist_asset_metadata",
        _persist,
        raising=True,
    )

    monkeypatch.setattr(
        "retrovue.cli.commands._ops.collection_ingest_service.handle_ingest",
        lambda payload: {"editorial": {}, "resolved_fields": {"station_ops": {"content_class": "cartoon"}}},  # noqa: E501
        raising=True,
    )

    collection = _fake_collection()
    importer = _fake_importer()

    service.ingest_collection(collection=collection, importer=importer)

    assert calls["kwargs"] is not None
    assert calls["kwargs"]["station_ops"] == {"content_class": "cartoon"}


def test_relationships_triggers_persistence(service: CollectionIngestService, monkeypatch: pytest.MonkeyPatch) -> None:
    """B-22: relationships block is persisted via helper from handler resolved_fields."""

    calls: dict[str, Any] = {"kwargs": None}

    def _persist(db, asset, *, editorial=None, probed=None, station_ops=None, relationships=None, sidecar=None):  # noqa: ANN001
        calls["kwargs"] = {
            "editorial": editorial,
            "probed": probed,
            "station_ops": station_ops,
            "relationships": relationships,
            "sidecar": sidecar,
        }

    monkeypatch.setattr(
        "retrovue.cli.commands._ops.collection_ingest_service.persist_asset_metadata",
        _persist,
        raising=True,
    )

    monkeypatch.setattr(
        "retrovue.cli.commands._ops.collection_ingest_service.handle_ingest",
        lambda payload: {"editorial": {}, "resolved_fields": {"relationships": {"series_id": "s-1"}}},  # noqa: E501
        raising=True,
    )

    collection = _fake_collection()
    importer = _fake_importer()

    service.ingest_collection(collection=collection, importer=importer)

    assert calls["kwargs"] is not None
    assert calls["kwargs"]["relationships"] == {"series_id": "s-1"}


def test_sidecar_triggers_persistence(service: CollectionIngestService, monkeypatch: pytest.MonkeyPatch) -> None:
    """B-22: sidecar block is persisted via helper from handler resolved_fields."""

    calls: dict[str, Any] = {"kwargs": None}

    def _persist(db, asset, *, editorial=None, probed=None, station_ops=None, relationships=None, sidecar=None):  # noqa: ANN001
        calls["kwargs"] = {
            "editorial": editorial,
            "probed": probed,
            "station_ops": station_ops,
            "relationships": relationships,
            "sidecar": sidecar,
        }

    monkeypatch.setattr(
        "retrovue.cli.commands._ops.collection_ingest_service.persist_asset_metadata",
        _persist,
        raising=True,
    )

    monkeypatch.setattr(
        "retrovue.cli.commands._ops.collection_ingest_service.handle_ingest",
        lambda payload: {"editorial": {}, "resolved_fields": {"sidecar": {"asset_type": "movie"}}},  # noqa: E501
        raising=True,
    )

    collection = _fake_collection()
    importer = _fake_importer()

    service.ingest_collection(collection=collection, importer=importer)

    assert calls["kwargs"] is not None
    assert calls["kwargs"]["sidecar"] == {"asset_type": "movie"}


