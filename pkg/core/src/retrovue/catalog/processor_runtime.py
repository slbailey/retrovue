"""
Processor runtime: shared ProcessingContext, run recording, single-transaction persist.

Phase 4: formal runtime per ProcessorExecutionContract. Load once, run processors
sequentially (no DB per processor), validate, persist asset + processor_runs in one transaction.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import structlog
from sqlalchemy.orm import Session

from ..adapters.importers.base import DiscoveredItem
from ..adapters.registry import ENRICHERS
from ..domain.entities import (
    Asset,
    AssetEditorial,
    AssetProbed,
    Collection,
    ProcessorRun,
)
from ..infra.metadata.persistence import persist_asset_metadata

from .processor_capability import get_capability, get_processors_for_target

logger = structlog.get_logger(__name__)

__all__ = [
    "ProcessorResult",
    "ExecutionContext",
    "ProcessingContext",
    "item_to_processor_result",
    "validate_processor_result",
    "execute_job",
]

RUN_STATUS_COMPLETED = "completed"
RUN_STATUS_FAILED = "failed"
DEFAULT_PROCESSOR_VERSION = "0.1.0"


# ---------------------------------------------------------------------------
# Context and result types (ProcessorExecutionContract)
# ---------------------------------------------------------------------------


@dataclass
class ProcessorResult:
    """Structured output from a processor. Conforms to ProcessorMetadataContract produced_metadata."""

    metadata: dict[str, Any]
    flexible: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ExecutionContext:
    """Per-processor-invocation read-only context. Processors MUST NOT perform direct DB reads/writes."""

    processor_id: str
    target_type: str
    target_id: uuid.UUID
    job_id: uuid.UUID
    execution_timestamp: datetime


@dataclass
class ProcessingContext:
    """
    Shared in-memory context for one job. Built once; processors receive read-only view.

    Holds target entity, existing metadata, and mutable_changes (merged processor results).
    No DB reads/writes per processor—only one load at start and one persist at end.
    """

    target_entity: Asset
    existing_probed: dict[str, Any]
    existing_editorial: dict[str, Any]
    mutable_changes: dict[str, Any] = field(default_factory=dict)
    mutable_probed: dict[str, Any] = field(default_factory=dict)
    mutable_editorial: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Adapter and validation
# ---------------------------------------------------------------------------


def item_to_processor_result(item: Any, processor_id: str) -> ProcessorResult:
    """Extract from enricher item the fields that the processor produces (structured result)."""
    cap = get_capability(processor_id)
    metadata: dict[str, Any] = {}
    if cap:
        labels = getattr(item, "raw_labels", None) or []
        for key in cap.produced_metadata:
            val = _extract_label(labels, key)
            if val is not None:
                if key == "duration_ms":
                    try:
                        metadata[key] = int(val)
                    except (ValueError, TypeError):
                        pass
                else:
                    metadata[key] = val
        probed = getattr(item, "probed", None) or {}
        for key in cap.produced_metadata:
            if key not in metadata and key in probed:
                v = probed[key]
                if key == "duration_ms" and v is not None:
                    try:
                        metadata[key] = int(v)
                    except (ValueError, TypeError):
                        pass
                else:
                    metadata[key] = v
        editorial = getattr(item, "editorial", None) or {}
        for key in cap.produced_metadata:
            if key not in metadata and key in editorial:
                metadata[key] = editorial[key]
    flexible: dict[str, Any] = {}
    if hasattr(item, "probed") and item.probed:
        flexible.setdefault("probed", dict(item.probed))
    if hasattr(item, "editorial") and item.editorial:
        flexible.setdefault("editorial", dict(item.editorial))
    return ProcessorResult(metadata=metadata, flexible=flexible)


def validate_processor_result(result: ProcessorResult, processor_id: str) -> None:
    """Assert result.metadata only contains keys in the processor's produced_metadata. Raise ValueError if invalid."""
    cap = get_capability(processor_id)
    if not cap:
        return
    allowed = set(cap.produced_metadata)
    for key in result.metadata:
        if key not in allowed:
            raise ValueError(f"Processor {processor_id} produced disallowed metadata key: {key}")


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


def _context_to_item(ctx: ProcessingContext, path_uri: str, collection_name: str = "") -> DiscoveredItem:
    """Build a DiscoveredItem from the current context for enricher.enrich(item)."""
    asset = ctx.target_entity
    probed = {**ctx.existing_probed, **ctx.mutable_probed}
    editorial = {**ctx.existing_editorial, **ctx.mutable_editorial}
    labels: list[str] = []
    for k, v in ctx.mutable_changes.items():
        if v is not None:
            labels.append(f"{k}:{v}")
    for k, v in ctx.mutable_probed.items():
        if k not in ctx.mutable_changes and v is not None:
            labels.append(f"{k}:{v}")
    return DiscoveredItem(
        path_uri=path_uri,
        provider_key=getattr(asset, "provider_key", None),
        raw_labels=labels,
        size=asset.size,
        probed=probed,
        editorial=editorial,
    )


def _compute_input_fingerprint(asset: Asset) -> str:
    """Fingerprint of target at run start for staleness detection."""
    parts = [
        str(asset.uuid),
        str(getattr(asset, "file_size", None) or getattr(asset, "size", "")),
        str(getattr(asset, "file_mtime", "")),
    ]
    return "|".join(parts)


def execute_job(db: Session, job: Any) -> None:
    """
    Load target once, build ProcessingContext, run processors (no DB per processor),
    then persist asset + processor_runs in a single transaction.

    On exception re-raise so the worker marks the job failed.
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

    # Load existing metadata once
    existing_probed: dict[str, Any] = {}
    existing_editorial: dict[str, Any] = {}
    try:
        probed_row = db.get(AssetProbed, asset.uuid)
        if probed_row and probed_row.payload:
            existing_probed = dict(probed_row.payload)
    except Exception:
        pass
    try:
        ed_row = db.get(AssetEditorial, asset.uuid)
        if ed_row and ed_row.payload:
            existing_editorial = dict(ed_row.payload)
    except Exception:
        pass

    input_fingerprint = _compute_input_fingerprint(asset)
    ctx = ProcessingContext(
        target_entity=asset,
        existing_probed=existing_probed,
        existing_editorial=existing_editorial,
    )

    processor_ids = get_processors_for_target(job.target_type)
    run_records: list[dict[str, Any]] = []

    for processor_id in processor_ids:
        enricher = _enricher_instance(processor_id, collection_name)
        if enricher is None:
            continue

        started_at = datetime.now(UTC)
        run_id = uuid.uuid4()
        run_record: dict[str, Any] = {
            "run_id": run_id,
            "job_id": job.id,
            "processor_id": processor_id,
            "target_type": job.target_type,
            "target_id": job.target_id,
            "processor_version": DEFAULT_PROCESSOR_VERSION,
            "input_fingerprint": input_fingerprint,
            "status": RUN_STATUS_COMPLETED,
            "started_at": started_at,
            "completed_at": None,
            "error_message": None,
        }
        exec_ctx = ExecutionContext(
            processor_id=processor_id,
            target_type=job.target_type,
            target_id=job.target_id,
            job_id=job.id,
            execution_timestamp=started_at,
        )
        logger.info(
            "processor_started",
            processor_id=processor_id,
            target_type=job.target_type,
            target_id=str(job.target_id),
            job_id=str(job.id),
        )
        try:
            item = _context_to_item(ctx, path_uri, collection_name)
            item = enricher.enrich(item)
            result = item_to_processor_result(item, processor_id)
            validate_processor_result(result, processor_id)
            # Merge into context (no DB write)
            ctx.mutable_changes.update(result.metadata)
            for k, v in result.metadata.items():
                if k in ("duration_ms", "video_codec", "audio_codec", "container", "bitrate", "resolution"):
                    ctx.mutable_probed[k] = v
                elif k in ("loudness_lufs", "gain_db", "loudness_range_lu"):
                    ctx.mutable_probed[k] = v
                elif k in ("interstitial_type",):
                    ctx.mutable_editorial[k] = v
            completed_at = datetime.now(UTC)
            run_record["completed_at"] = completed_at
            duration_ms = (completed_at - started_at).total_seconds() * 1000
            logger.info(
                "processor_completed",
                processor_id=processor_id,
                duration_ms=round(duration_ms),
            )
        except Exception as e:
            completed_at = datetime.now(UTC)
            run_record["status"] = RUN_STATUS_FAILED
            run_record["completed_at"] = completed_at
            run_record["error_message"] = str(e)
            logger.warning(
                "processor_failed",
                processor_id=processor_id,
                error=str(e),
            )
            run_records.append(run_record)
            # Persist run rows for every processor that was invoked (including failed)
            for rec in run_records:
                db.add(
                    ProcessorRun(
                        run_id=rec["run_id"],
                        job_id=rec["job_id"],
                        processor_id=rec["processor_id"],
                        target_type=rec["target_type"],
                        target_id=rec["target_id"],
                        processor_version=rec.get("processor_version"),
                        input_fingerprint=rec.get("input_fingerprint"),
                        status=rec["status"],
                        started_at=rec["started_at"],
                        completed_at=rec.get("completed_at"),
                        error_message=rec.get("error_message"),
                    )
                )
            db.commit()
            raise
        run_records.append(run_record)

    # Single transaction: apply mutable changes to asset and persist; insert processor_runs
    asset = ctx.target_entity
    if ctx.mutable_changes.get("duration_ms") is not None:
        try:
            asset.duration_ms = int(ctx.mutable_changes["duration_ms"])
        except (ValueError, TypeError):
            pass
    for key in ("video_codec", "audio_codec", "container"):
        if ctx.mutable_changes.get(key) is not None:
            setattr(asset, key, ctx.mutable_changes[key])
    probed_to_persist = {**ctx.existing_probed, **ctx.mutable_probed}
    if probed_to_persist:
        persist_asset_metadata(db, asset, probed=probed_to_persist)
    editorial_to_persist = {**ctx.existing_editorial, **ctx.mutable_editorial}
    if editorial_to_persist:
        existing_ed = db.get(AssetEditorial, asset.uuid)
        if existing_ed:
            existing_ed.payload = editorial_to_persist
            db.add(existing_ed)
        else:
            db.add(AssetEditorial(asset_uuid=asset.uuid, payload=editorial_to_persist))

    for rec in run_records:
        db.add(
            ProcessorRun(
                run_id=rec["run_id"],
                job_id=rec["job_id"],
                processor_id=rec["processor_id"],
                target_type=rec["target_type"],
                target_id=rec["target_id"],
                processor_version=rec.get("processor_version"),
                input_fingerprint=rec.get("input_fingerprint"),
                status=rec["status"],
                started_at=rec["started_at"],
                completed_at=rec.get("completed_at"),
                error_message=rec.get("error_message"),
            )
        )
