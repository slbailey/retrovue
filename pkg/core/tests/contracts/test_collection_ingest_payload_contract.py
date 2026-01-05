"""
Contract: docs/contracts/resources/CollectionIngestContract.md
Rules covered:
- B-20: ingest builds handler payload with importer_name, asset_type, source_uri, editorial, probed, sidecars
"""

from __future__ import annotations

from typing import Any

import pytest

from retrovue.adapters.importers.base import DiscoveredItem
from retrovue.cli.commands._ops.collection_ingest_service import CollectionIngestService


def _fake_collection() -> Any:
    class _C:
        uuid = "00000000-0000-0000-0000-000000000002"
        name = "Test Collection"
        sync_enabled = True
        ingestible = True

    return _C()


def _fake_importer() -> Any:
    class _I:
        name = "filesystem"

        def validate_ingestible(self, collection: Any) -> bool:  # noqa: ARG002
            return True

        def discover(self) -> list[DiscoveredItem]:
            return [
                DiscoveredItem(
                    path_uri="file:///tmp/a.mkv",
                    editorial={"title": "Akira"},
                    sidecar={"asset_type": "movie"},
                    probed={"duration_ms": 120000},
                )
            ]

        def resolve_local_uri(self, item: Any, *, collection: Any | None = None, path_mappings=None) -> str:  # noqa: ARG002
            return "file:///tmp/a.mkv"

    return _I()


@pytest.fixture
def service(monkeypatch: pytest.MonkeyPatch) -> CollectionIngestService:
    class _DB:
        def add(self, _obj: Any) -> None:
            return None

        def flush(self) -> None:
            return None

        def scalar(self, _stmt: Any) -> Any:
            return None


    monkeypatch.setattr("retrovue.cli.commands._ops.collection_ingest_service.ENRICHERS", {}, raising=True)
    return CollectionIngestService(_DB())


def test_b20_ingest_builds_handler_payload(service: CollectionIngestService, monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {"payload": None}

    def _handle(payload: dict[str, Any]) -> dict[str, Any]:
        captured["payload"] = payload
        return {"editorial": payload.get("editorial"), "resolved_fields": {}}

    monkeypatch.setattr(
        "retrovue.cli.commands._ops.collection_ingest_service.handle_ingest",
        _handle,
        raising=True,
    )

    collection = _fake_collection()
    importer = _fake_importer()

    service.ingest_collection(collection=collection, importer=importer)

    pl = captured["payload"]
    assert pl is not None
    # Required keys
    assert pl.get("importer_name") == "filesystem"
    assert pl.get("source_uri") == "file:///tmp/a.mkv"
    # Domains
    assert pl.get("editorial") == {"title": "Akira"}
    assert pl.get("probed") == {"duration_ms": 120000}
    assert isinstance(pl.get("sidecars", []), list)
    assert pl.get("sidecars", [])[0] == {"asset_type": "movie"}


