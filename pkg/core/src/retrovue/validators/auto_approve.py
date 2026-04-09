"""
Auto-approval workflow — validates an asset and transitions it to ready if
all validators pass.

Per INV-ASSET-STATE-MACHINE-001, the transition path is:
  new → enriching → ready

Per INV-CATALOG-READY-SCHEDULABLE-001, a ``ready`` asset is the trust
boundary for scheduling — no further validation is required downstream.

Auto-approval sets ``approved_for_broadcast = True`` on the ready asset.
"""

from __future__ import annotations

import structlog
from typing import Any

from ..domain.entities import validate_state_transition
from .pipeline import ValidationPipeline
from .result import ValidationResult

logger = structlog.get_logger(__name__)


def try_auto_approve(asset: Any, pipeline: ValidationPipeline) -> ValidationResult:
    """Run validators and, if all pass, transition *asset* to ready.

    Returns the aggregate ValidationResult regardless of outcome.
    The caller can inspect ``result.passed`` to determine whether
    auto-approval succeeded.

    State transitions are validated via ``validate_state_transition``
    per INV-ASSET-STATE-MACHINE-001.
    """
    result = pipeline.run(asset)

    if not result.passed:
        logger.debug(
            "auto_approve_validation_failed",
            asset_uuid=str(getattr(asset, "uuid", "?")),
            errors=[e.code for e in result.errors],
        )
        return result

    # Transition new → enriching → ready in one pass
    current = getattr(asset, "state", "new")
    if current == "new":
        validate_state_transition(current, "enriching")
        validate_state_transition("enriching", "ready")
        asset.state = "ready"
        asset.approved_for_broadcast = True
        logger.debug(
            "auto_approve_success",
            asset_uuid=str(getattr(asset, "uuid", "?")),
            path="new → enriching → ready",
        )
    elif current == "enriching":
        validate_state_transition(current, "ready")
        asset.state = "ready"
        asset.approved_for_broadcast = True
        logger.debug(
            "auto_approve_success",
            asset_uuid=str(getattr(asset, "uuid", "?")),
            path="enriching → ready",
        )

    return result
