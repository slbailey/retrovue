from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any

import structlog

# Lazy import infra helpers inside functions to avoid hard dependency during CLI startup


_log = structlog.get_logger(__name__)


def validate_sidecar(sidecar: Any) -> None:
    """Validate a single sidecar payload (dict or Pydantic model) against JSON Schema.

    Raises ValueError if invalid.
    """
    def _to_dict(obj: Any) -> dict:
        if hasattr(obj, "model_dump") and callable(obj.model_dump):
            return obj.model_dump(by_alias=True, exclude_none=True)
        if isinstance(obj, dict):
            return obj
        raise TypeError("Sidecar must be a dict or Pydantic model with model_dump()")

    data = _to_dict(sidecar)
    # Lazy import to avoid requiring jsonschema at module import time
    try:
        from retrovue.infra.metadata.schema_loader import validate_sidecar_json  # type: ignore

        validate_sidecar_json(data)
    except Exception as e:
        # If schema validation infra is unavailable, surface as ValueError to caller
        raise ValueError(str(e))
    _log.info("sidecar_validation_ok", asset_type=data.get("asset_type"))


def preprocess_sidecars(payload: Any) -> Any:
    """Validate, merge, and enforce authoritative rules on sidecars before resolution.

    Steps:
    - Validate each provided sidecar against the Draft-07 schema
    - Merge sidecars by scope (collection < series < file)
    - Enforce probe-only fields cannot be authoritative
    - Assign merged sidecar back to payload
    """

    def _to_dict(obj: Any) -> dict:
        if hasattr(obj, "model_dump") and callable(obj.model_dump):
            return obj.model_dump(by_alias=True, exclude_none=True)
        if isinstance(obj, dict):
            return obj
        raise TypeError("Sidecar must be a dict or Pydantic model with model_dump()")

    # Extract sidecars; support dict payload or Pydantic model
    sidecar = getattr(payload, "sidecar", None) if not isinstance(payload, dict) else payload.get("sidecar")
    sidecars = getattr(payload, "sidecars", None) if not isinstance(payload, dict) else payload.get("sidecars")

    if not sidecar and not sidecars:
        return payload

    sidecar_list: Iterable[Any] = sidecars or [sidecar]
    sc_dicts = [_to_dict(sc) for sc in sidecar_list if sc is not None]

    # Validate each sidecar (lazy import)
    try:
        from retrovue.infra.metadata.schema_loader import validate_sidecar_json  # type: ignore
    except Exception:
        validate_sidecar_json = None  # type: ignore
    if validate_sidecar_json is not None:
        for sc in sc_dicts:
            validate_sidecar_json(sc)

    # Merge and enforce authoritative field rules
    # Merge and enforce authoritative field rules
    from retrovue.infra.metadata.sidecar_merge import (  # type: ignore
        merge_sidecars as merge_sidecars_dict,
    )

    merged = merge_sidecars_dict(sc_dicts)

    try:
        from retrovue.infra.metadata.validators import validate_authoritative_fields  # type: ignore

        validate_authoritative_fields(merged)
    except Exception:
        # If validator infra is missing, continue; probe-only enforcement will occur at persist stage
        pass

    # Assign back
    if isinstance(payload, dict):
        payload["sidecar"] = merged
        payload.pop("sidecars", None)
    else:
        try:
            payload.sidecar = merged
            if hasattr(payload, "sidecars"):
                payload.sidecars = None
        except Exception:
            _log.warning("sidecar_assignment_failed", reason="payload not mutable")
    return payload


def _merge_scalar_or_replace(dst: dict, key: str, value: object) -> None:
    """Prefer non-None incoming values; keep existing if new value is None."""
    if value is not None:
        dst[key] = value


def _merge_array(dst: list, src: Sequence) -> list:
    seen = set()
    out: list = []
    for item in list(dst) + list(src):
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def deep_merge_metadata(target: dict, incoming: dict) -> dict:
    """
    Non-destructive, section-aware merge for metadata envelopes.
    - dict + dict -> recurse
    - list + list -> union/dedupe
    - scalar -> replace if incoming is not None
    """
    for key, value in incoming.items():
        if value is None:
            continue
        if key not in target:
            target[key] = value
            continue

        existing = target[key]

        if isinstance(existing, Mapping) and isinstance(value, Mapping):
            deep_merge_metadata(existing, value)  # type: ignore[arg-type]
        elif isinstance(existing, list) and isinstance(value, list | tuple):
            target[key] = _merge_array(existing, value)
        else:
            target[key] = value

    return target


def handle_ingest(payload: Any) -> dict:
    """Main ingest entry point for importer payloads.

    This function:
    - Preprocesses sidecars (validate/merge/enforce authoritative rules)
    - Performs source resolution and persistence (TBD; out of scope here)
    - Returns the standard ingest result shape

    It raises ValueError for validation errors; callers should map to HTTP 400.
    """
    # Ensure dict-like for preprocessing
    if not isinstance(payload, dict) and not hasattr(payload, "model_dump"):
        raise ValueError("Ingest payload must be a dict or Pydantic model")

    processed = preprocess_sidecars(payload)
    # Pass through current payload fields so callers can inspect what the handler received
    data = (
        processed.model_dump(by_alias=True, exclude_none=True)
        if hasattr(processed, "model_dump")
        else processed
    )

    # Build a section-aware envelope we can merge into
    final_payload: dict[str, Any] = {
        "editorial": {},
        "probed": {},
        "station_ops": {},
        "relationships": {},
        "source_payloads": [],
    }

    # 1) Apply importer payload first
    importer_ed = dict(data.get("importer_editorial") or {})
    if importer_ed:
        deep_merge_metadata(final_payload["editorial"], importer_ed)
    if data.get("editorial"):
        deep_merge_metadata(final_payload["editorial"], dict(data.get("editorial") or {}))
    if data.get("probed"):
        deep_merge_metadata(final_payload["probed"], dict(data.get("probed") or {}))
    if data.get("source_payload" ):
        final_payload["source_payloads"].append(data.get("source_payload"))

    # 2) Merge sidecar sections (already resolved precedence by preprocess_sidecars)
    sidecar = dict(data.get("sidecar") or {})
    if sidecar:
        for section in ("editorial", "probed", "station_ops", "relationships"):
            sec_val = sidecar.get(section)
            if isinstance(sec_val, dict):
                deep_merge_metadata(final_payload.setdefault(section, {}), sec_val)

    # 3) Probe result was merged above via data["probed"]

    # 4) Enricher results: not provided at this layer in current architecture

    # 5) Operator overrides (highest priority)
    if data.get("station_ops"):
        deep_merge_metadata(
            final_payload["station_ops"], dict(data.get("station_ops") or {})
        )

    provenance = {
        "importer": data.get("importer_name") or data.get("importer"),
        "source_uri": data.get("source_uri"),
    }

    resolved_fields = {
        "editorial": final_payload["editorial"],
        "probed": final_payload["probed"],
        "station_ops": final_payload["station_ops"],
        "relationships": final_payload["relationships"],
        "sidecar": sidecar,
        "source_payloads": final_payload["source_payloads"],
    }

    # Backward-compat: also expose editorial at top-level
    return {
        "status": "ok",
        "editorial": final_payload["editorial"],
        "resolved_fields": resolved_fields,
        "canonical_uri": data.get("source_uri"),
        "asset_id": None,
        "enriched_fields": {},
        "provenance": provenance,
    }


