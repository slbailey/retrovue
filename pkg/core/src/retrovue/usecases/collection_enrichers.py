from __future__ import annotations

import json as _json
from hashlib import sha256 as _sha256
from typing import Any

from sqlalchemy.orm import Session

from ..adapters.importers.base import DiscoveredItem
from ..adapters.registry import ENRICHERS
from ..domain.entities import Asset, Collection, Enricher


def _resolve_collection(db: Session, selector: str) -> Collection:
    """Resolve a collection by UUID, external_id, or case-insensitive name.

    Raises ValueError when not found or ambiguous by name.
    """
    # Try UUID (exact)
    try:
        import uuid as _uuid

        _uuid.UUID(selector)
        col = db.query(Collection).filter(Collection.uuid == selector).first()
        if col:
            return col
    except Exception:
        pass

    # Try external_id (exact)
    col = db.query(Collection).filter(Collection.external_id == selector).first()
    if col:
        return col

    # Try name (case-insensitive, single match)
    matches = db.query(Collection).filter(Collection.name.ilike(selector)).all()
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        raise ValueError(
            f"Multiple collections named '{selector}' exist. Please specify the UUID."
        )
    raise ValueError(f"Collection '{selector}' not found")


def _validate_enricher_exists(db: Session, enricher_id: str) -> None:
    """Validate an enricher exists by its enricher_id."""
    exists = (
        db.query(Enricher).filter(Enricher.enricher_id == enricher_id).first() is not None
    )
    if not exists:
        raise ValueError(f"Enricher not found: {enricher_id}")


def attach_enricher_to_collection(
    db: Session, *, collection_selector: str, enricher_id: str, priority: int
) -> dict[str, Any]:
    """Attach or update an enricher attachment on a collection.

    - Validates collection and enricher
    - Adds or updates entry in collection.config["enrichers"]
    - Does not commit (caller handles UnitOfWork)
    """
    collection = _resolve_collection(db, collection_selector)
    _validate_enricher_exists(db, enricher_id)

    cfg = dict(collection.config or {})
    enrichers = list(cfg.get("enrichers", []))

    # Normalize entries as dicts {enricher_id, priority}
    updated = False
    for entry in enrichers:
        if isinstance(entry, dict) and entry.get("enricher_id") == enricher_id:
            entry["priority"] = int(priority)
            updated = True
            break
    if not updated:
        enrichers.append({"enricher_id": enricher_id, "priority": int(priority)})

    # Sort by priority ascending
    try:
        enrichers.sort(key=lambda e: int(e.get("priority", 0)))
    except Exception:
        pass

    cfg["enrichers"] = enrichers
    collection.config = cfg
    db.add(collection)

    return {
        "collection_id": str(collection.uuid),
        "collection_name": collection.name,
        "enricher_id": enricher_id,
        "priority": int(priority),
        "status": "attached",
    }


def detach_enricher_from_collection(
    db: Session, *, collection_selector: str, enricher_id: str
) -> dict[str, Any]:
    """Detach an enricher from a collection.

    - Validates collection and enricher existence (enricher may have been deleted; allow detach)
    - Removes entry from collection.config["enrichers"] if present
    - Does not commit (caller handles UnitOfWork)
    """
    collection = _resolve_collection(db, collection_selector)

    cfg = dict(collection.config or {})
    enrichers = list(cfg.get("enrichers", []))

    new_list: list[dict[str, Any]] = []
    for entry in enrichers:
        if isinstance(entry, dict) and entry.get("enricher_id") == enricher_id:
            # skip to remove
            continue
        new_list.append(entry)

    cfg["enrichers"] = new_list
    collection.config = cfg
    db.add(collection)

    return {
        "collection_id": str(collection.uuid),
        "collection_name": collection.name,
        "enricher_id": enricher_id,
        "status": "detached",
    }


__all__ = [
    "attach_enricher_to_collection",
    "detach_enricher_from_collection",
    "apply_enrichers_to_collection",
]


def apply_enrichers_to_collection(
    db: Session,
    *,
    collection_selector: str,
    auto_ready_threshold: float = 0.80,
    review_threshold: float = 0.50,
    max_assets: int | None = None,
) -> dict[str, Any]:
    """Apply currently attached ingest-scope enrichers to existing assets in a collection.

    - Targets assets where state='new' OR last_enricher_checksum differs from current pipeline
    - Updates technical fields from enricher labels
    - Sets last_enricher_checksum to current pipeline checksum
    - Recomputes confidence and auto-promotes to ready/approved when threshold is met
    - Does not commit; caller must commit/rollback
    """
    collection = _resolve_collection(db, collection_selector)

    # Load configured enrichers for this collection in priority order
    cfg = dict(collection.config or {})
    configured = cfg.get("enrichers", []) if isinstance(cfg.get("enrichers"), list) else []

    from ..domain.entities import Enricher as EnricherRow

    pipeline: list[Any] = []
    signature: list[dict[str, Any]] = []
    for entry in configured:
        try:
            enricher_id = entry.get("enricher_id") if isinstance(entry, dict) else None
            priority = int(entry.get("priority", 0)) if isinstance(entry, dict) else 0
            if not enricher_id:
                continue
            row = (
                db.query(EnricherRow).filter(EnricherRow.enricher_id == enricher_id).first()
            )
            if not row or getattr(row, "scope", "ingest") != "ingest":
                continue
            cls = ENRICHERS.get(row.type)
            instance = cls(**(row.config or {})) if cls else None
            if instance is None:
                continue
            pipeline.append((priority, enricher_id, instance))
        except Exception:
            continue
    pipeline.sort(key=lambda t: (t[0], t[1]))
    signature = [{"enricher_id": eid, "priority": pr} for (pr, eid, _) in pipeline]

    # If no pipeline is configured, this is a no-op
    if not pipeline:
        return {
            "collection_id": str(collection.uuid),
            "collection_name": collection.name,
            "pipeline_checksum": None,
            "stats": {"assets_considered": 0, "assets_enriched": 0, "assets_auto_ready": 0, "errors": []},
        }

    # Compute pipeline checksum
    try:
        sig_bytes = _json.dumps(signature, sort_keys=True).encode("utf-8")
        pipeline_checksum = _sha256(sig_bytes).hexdigest()
    except Exception:
        pipeline_checksum = None

    # Select assets to process
    q = db.query(Asset).filter(Asset.collection_uuid == collection.uuid, Asset.is_deleted.is_(False))
    q = q.filter(
        (Asset.state == "new") | (Asset.last_enricher_checksum.is_(None)) | (Asset.last_enricher_checksum != pipeline_checksum)
    )
    if isinstance(max_assets, int) and max_assets > 0:
        assets = q.limit(max_assets).all()
    else:
        assets = q.all()

    def _extract_label_value(labels: list[str] | None, key: str) -> str | None:
        if not labels:
            return None
        prefix = f"{key}:"
        for label in labels:
            if isinstance(label, str) and label.startswith(prefix):
                return label[len(prefix) :]
        return None

    def _compute_confidence_from_labels(item: DiscoveredItem) -> float:
        score = 0.0
        try:
            size_ok = (item.size or 0) > 0
            if size_ok:
                score += 0.2
            labels = item.raw_labels or []
            dur = _extract_label_value(labels, "duration_ms")
            if dur is not None:
                try:
                    if int(dur) > 0:
                        score += 0.3
                except Exception:
                    pass
            if _extract_label_value(labels, "video_codec") is not None:
                score += 0.2
            if _extract_label_value(labels, "audio_codec") is not None:
                score += 0.1
            if _extract_label_value(labels, "container") is not None:
                score += 0.1
        except Exception:
            pass
        if score < 0.0:
            return 0.0
        if score > 1.0:
            return 1.0
        return score

    stats = {
        "assets_considered": len(assets),
        "assets_enriched": 0,
        "assets_auto_ready": 0,
        "errors": [],
    }

    for asset in assets:
        try:
            # Construct a DiscoveredItem for enrichment based on stored canonical_uri
            path_uri = asset.canonical_uri or asset.uri or ""
            if not path_uri:
                continue
            item = DiscoveredItem(path_uri=path_uri, raw_labels=[], size=asset.size)
            # Run pipeline
            for _, _, enr in pipeline:
                try:
                    item = enr.enrich(item)
                except Exception as enr_exc:
                    stats["errors"].append(str(enr_exc))
            # Map labels back to asset fields
            labels = item.raw_labels or []
            dur_val = _extract_label_value(labels, "duration_ms")
            if dur_val is not None:
                try:
                    asset.duration_ms = int(dur_val)
                except Exception:
                    pass
            vid_val = _extract_label_value(labels, "video_codec")
            if vid_val is not None:
                asset.video_codec = vid_val
            aud_val = _extract_label_value(labels, "audio_codec")
            if aud_val is not None:
                asset.audio_codec = aud_val
            cont_val = _extract_label_value(labels, "container")
            if cont_val is not None:
                asset.container = cont_val

            # Record pipeline checksum
            if pipeline_checksum:
                asset.last_enricher_checksum = pipeline_checksum

            # Recompute confidence and auto-promote if eligible
            conf = _compute_confidence_from_labels(item)
            if conf >= auto_ready_threshold:
                asset.state = "ready"
                asset.approved_for_broadcast = True
                stats["assets_auto_ready"] += 1

            stats["assets_enriched"] += 1
            db.add(asset)
        except Exception as e:
            stats["errors"].append(str(e))

    return {
        "collection_id": str(collection.uuid),
        "collection_name": collection.name,
        "pipeline_checksum": pipeline_checksum,
        "stats": stats,
    }

