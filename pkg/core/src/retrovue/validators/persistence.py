"""
Validator result persistence per INV-VALIDATOR-RESULT-PERSISTENCE-001.

Every validator result that gates an asset state transition MUST be persisted.
The persisted record conforms to INV-VALIDATOR-OUTPUT-SHAPE-001 without
transformation or lossy compression.

This module provides the in-process persistence store. Production usage
will back this with the database; the contract tests validate the round-trip
shape guarantee independent of storage backend.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .result import (
    ValidationResult,
    ValidatorEntry,
    ValidatorError,
    ValidatorWarning,
)


@dataclass(frozen=True)
class PersistedValidationRecord:
    """A persisted validator result with provenance metadata."""

    asset_id: str
    timestamp: datetime
    result: ValidationResult


def _serialize_result(result: ValidationResult) -> dict:
    """Serialize a ValidationResult to a plain dict for storage."""
    return {
        "status": result.status,
        "errors": [
            {"code": e.code, "validator": e.validator, "message": e.message}
            for e in result.errors
        ],
        "warnings": [
            {"code": w.code, "validator": w.validator, "message": w.message}
            for w in result.warnings
        ],
        "validators": {
            k: {"status": v.status} for k, v in result.validators.items()
        },
    }


def _deserialize_result(data: dict) -> ValidationResult:
    """Deserialize a plain dict back to a ValidationResult.

    Guarantees exact round-trip: no field loss, no type coercion.
    """
    return ValidationResult(
        status=data["status"],
        errors=[
            ValidatorError(code=e["code"], validator=e["validator"], message=e["message"])
            for e in data["errors"]
        ],
        warnings=[
            ValidatorWarning(code=w["code"], validator=w["validator"], message=w["message"])
            for w in data["warnings"]
        ],
        validators={
            k: ValidatorEntry(status=v["status"])
            for k, v in data["validators"].items()
        },
    )


class ValidationResultStore:
    """In-process validation result store.

    Provides persist/retrieve with exact round-trip shape guarantee.
    Production callers should integrate with the database layer;
    this store validates the serialization contract.
    """

    def __init__(self) -> None:
        self._records: dict[str, tuple[str, datetime, dict]] = {}

    def persist(
        self,
        *,
        asset_id: str,
        timestamp: datetime,
        result: ValidationResult,
    ) -> None:
        """Persist a validation result for an asset.

        The result is serialized to a plain dict to prove that
        round-trip deserialization preserves the canonical shape.
        """
        self._records[asset_id] = (asset_id, timestamp, _serialize_result(result))

    def retrieve(self, asset_id: str) -> PersistedValidationRecord | None:
        """Retrieve the most recent validation result for an asset.

        Returns None if no result has been persisted for this asset.
        """
        entry = self._records.get(asset_id)
        if entry is None:
            return None
        stored_id, stored_ts, stored_data = entry
        return PersistedValidationRecord(
            asset_id=stored_id,
            timestamp=stored_ts,
            result=_deserialize_result(stored_data),
        )
