"""
Minimal processor runtime: execute one job by running applicable enrichers for the target.

Phase 3: placeholder; Phase 4 adds ProcessingContext, processor_runs, validation.
Contract: ProcessorJobQueueContract, ProcessorExecutionContract.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from ..adapters.importers.base import DiscoveredItem
from ..adapters.registry import ENRICHERS
from ..domain.entities import Asset, Collection
from ..infra.metadata.persistence import persist_asset_metadata

from .processor_capability import get_processors_for_target


def _extract_label(labels: list[str], key: str) -> str | None:
    prefix = f"{key}:"
    for label in labels:
        if isinstance(label, str) and label.startswith(prefix):
            return label[len(prefix) :]
    return None


def _enricher_instance(processor_id: str, collection_name: str = "") -> Any:
    cls = ENRICHERS.get(processor_id)
    if cls is None:
        return None
    try:
        if processor_id == "interstitial-type":
            return cls(collection_name=collection_name)
        return cls()
    except Exception:
        return None


def execute_job(db: Session, job: Any) -> None:
    """
    Load target (Asset), build minimal item, run processors for job.target_type, persist.

    On exception re-raise so the worker can mark the job failed.
    """
    asset = db.get(Asset, job.target_id)
    if asset is None:
        raise ValueError(f"Asset not found for target_id={job.target_id}")

    path_uri = (asset.canonical_uri or asset.uri or "").strip()
    if not path_uri:
        raise ValueError(f"Asset {asset.uuid} has no uri/canonical_uri for enrichment")

    collection_name = ""
    try:
        coll = db.get(Collection, asset.collection_uuid)
        if coll is not None:
            collection_name = getattr(coll, "name", "") or ""
    except Exception:
        pass

    item = DiscoveredItem(
        path_uri=path_uri,
        provider_key=getattr(asset, "provider_key", None),
        raw_labels=[],
        size=asset.size,
        probed={},
        editorial={},
    )

    processor_ids = get_processors_for_target(job.target_type)
    for processor_id in processor_ids:
        enricher = _enricher_instance(processor_id, collection_name)
        if enricher is None:
            continue
        item = enricher.enrich(item)

    labels = item.raw_labels or []
    dur_val = _extract_label(labels, "duration_ms")
    if dur_val is not None:
        try:
            asset.duration_ms = int(dur_val)
        except (ValueError, TypeError):
            pass
    vid_val = _extract_label(labels, "video_codec")
    if vid_val is not None:
        asset.video_codec = vid_val
    aud_val = _extract_label(labels, "audio_codec")
    if aud_val is not None:
        asset.audio_codec = aud_val
    cont_val = _extract_label(labels, "container")
    if cont_val is not None:
        asset.container = cont_val

    probed_data = item.probed or {}
    if asset.duration_ms is None and probed_data.get("duration_ms"):
        try:
            asset.duration_ms = int(probed_data["duration_ms"])
        except (ValueError, TypeError):
            pass

    if probed_data:
        persist_asset_metadata(db, asset, probed=probed_data)

    editorial_data = item.editorial or {}
    if editorial_data:
        from ..domain.entities import AssetEditorial

        existing_ed = db.get(AssetEditorial, asset.uuid)
        if existing_ed:
            merged = dict(existing_ed.payload or {})
            merged.update(editorial_data)
            existing_ed.payload = merged
            db.add(existing_ed)
        else:
            db.add(AssetEditorial(asset_uuid=asset.uuid, payload=dict(editorial_data)))
