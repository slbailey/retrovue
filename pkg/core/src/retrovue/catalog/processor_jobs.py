"""
Processor job enqueue API (stub in Phase 2; real implementation in Phase 3).

Contract: ProcessorJobQueueContract. Enqueue is no-op or log-only until ENABLE_PROCESSOR_QUEUE.
"""

from __future__ import annotations

import uuid

import structlog

logger = structlog.get_logger(__name__)


def enqueue_processor_jobs(
    asset_ids: list[uuid.UUID],
    processor_ids: list[str],
    *,
    db: object = None,
) -> None:
    """
    Stub: would enqueue processor jobs for the given assets.

    Phase 3 replaces this with real enqueue to processor_jobs table.
    """
    if asset_ids and processor_ids:
        logger.debug(
            "enqueue_processor_jobs_stub",
            asset_count=len(asset_ids),
            processor_ids=processor_ids,
        )
