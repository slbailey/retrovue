"""
Public API for CUN (Coming Up Next) synthesis pipeline.

This module provides the contract-defined API surface for CUN. It re-exports
from internal modules (cun_queue, cun_synthesis_worker) and adds pure functions
for template selection, cleanup eligibility, and segment resolution.

Contracts served:
    INV-CUN-FEATURE-FLAG-001 (gate)
    INV-CUN-SCHEDULE-SCOPED-001 (not a ProcessorJob)
    INV-CUN-RENDER-DEADLINE-001 (deadline check)
    INV-CUN-SKIP-IF-UNREADY-001 (skip unready)
    INV-CUN-PRIORITY-PLAYOUT-001 (playout-time ordering)
    INV-CUN-CACHE-DEDUP-001 (content-addressed hash)
    INV-CUN-DEDUP-BEFORE-RENDER-001 (pre-render dedup)
    INV-CUN-CACHE-UNTIL-USED-001 (retain until broadcast)
    INV-CUN-CACHE-SAFE-CLEANUP-001 (safe cleanup across shared hashes)
    INV-CUN-TEMPLATE-DETERMINISTIC-001 (deterministic selection)
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta
from typing import Any

from retrovue.domain.entities import CunRenderRequest
from retrovue.runtime.cun_queue import content_hash_for
from retrovue.runtime.cun_synthesis_worker import (
    CunTemplateConfig,
    run_loop,
    run_once,
)


# ---------------------------------------------------------------------------
# Re-export: INV-CUN-CACHE-DEDUP-001
# ---------------------------------------------------------------------------

def cun_content_hash(template_id: str, title: str) -> str:
    """Deterministic content hash: SHA256(template_id:title).

    INV-CUN-CACHE-DEDUP-001.
    """
    return content_hash_for(template_id, title)


# ---------------------------------------------------------------------------
# CunSynthesisWorker: facade over run_once / run_loop
# ---------------------------------------------------------------------------

class CunSynthesisWorker:
    """CUN synthesis worker facade.

    Wraps the functional run_once/run_loop API as a class for contract-test
    discoverability. Also exposes deadline-check logic as a static method
    so contract tests can verify INV-CUN-RENDER-DEADLINE-001 without DB.
    """

    run_once = staticmethod(run_once)
    run_loop = staticmethod(run_loop)

    @staticmethod
    def is_past_deadline(
        segment_start_utc: datetime,
        now: datetime,
        margin_ms: int,
    ) -> bool:
        """INV-CUN-RENDER-DEADLINE-001: True if now >= segment_start - margin."""
        deadline = segment_start_utc - timedelta(milliseconds=margin_ms)
        return now >= deadline


# ---------------------------------------------------------------------------
# Pure functions
# ---------------------------------------------------------------------------

def cun_select_template(
    *,
    channel_id: str,
    broadcast_day: str,
    block_index: int,
    templates: list[dict[str, Any]],
) -> dict[str, Any]:
    """INV-CUN-TEMPLATE-DETERMINISTIC-001: SHA256-seeded deterministic selection.

    Same (channel_id, broadcast_day, block_index, templates) always returns the
    same template. Different inputs generally select different templates.
    """
    if not templates:
        raise ValueError("templates must not be empty")
    seed = f"{channel_id}:{broadcast_day}:{block_index}"
    h = hashlib.sha256(seed.encode("utf-8")).hexdigest()
    idx = int(h, 16) % len(templates)
    return templates[idx]


def cun_cleanup_eligible(
    segment_start_utc_list: list[datetime],
    now: datetime,
) -> bool:
    """INV-CUN-CACHE-SAFE-CLEANUP-001 + INV-CUN-CACHE-UNTIL-USED-001.

    A cached CUN render file is eligible for cleanup only when ALL referencing
    requests have segment_start_utc in the past.

    Returns True if all segments have aired (cleanup safe), False otherwise.
    """
    if not segment_start_utc_list:
        return True  # no references → safe to clean
    return all(s < now for s in segment_start_utc_list)


def ensure_cun_ready(
    segment: dict[str, Any],
    render_status: str | None,
    rendered_asset_path: str | None = None,
) -> dict[str, Any] | None:
    """INV-CUN-SKIP-IF-UNREADY-001: resolve a CUN segment or skip it.

    Args:
        segment: The CUN segment dict from schedule compilation.
        render_status: Status of the associated render request
            ("completed", "pending", "failed", "skipped", or None).
        rendered_asset_path: File path of the rendered asset (when completed).

    Returns:
        Resolved segment dict with rendered_asset_path if completed.
        None if unready (caller must skip the segment).

    This is the pure-logic core of the PBD's _ensure_cun_ready method.
    It never blocks, never waits, never touches DB — it just decides.
    """
    if render_status == "completed" and rendered_asset_path:
        resolved = dict(segment)
        resolved["rendered_asset_path"] = rendered_asset_path
        return resolved
    # Pending, failed, skipped, or None → skip the segment.
    return None


__all__ = [
    "CunRenderRequest",
    "CunSynthesisWorker",
    "CunTemplateConfig",
    "cun_content_hash",
    "cun_cleanup_eligible",
    "cun_select_template",
    "ensure_cun_ready",
]
