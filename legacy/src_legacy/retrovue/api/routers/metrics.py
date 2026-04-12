"""
Metrics endpoints for Retrovue.

This module provides metrics endpoints for monitoring and observability.
"""

from __future__ import annotations

from fastapi import APIRouter, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from ...infra.logging import get_logger

router = APIRouter()
logger = get_logger(__name__)


@router.get("/metrics")
async def get_metrics() -> Response:
    """
    Prometheus metrics endpoint.

    Returns:
        Response with Prometheus-formatted metrics
    """
    try:
        # Generate Prometheus metrics
        metrics_data = generate_latest()

        logger.debug("metrics_requested", metrics_size=len(metrics_data))

        return Response(content=metrics_data, media_type=CONTENT_TYPE_LATEST)
    except Exception as e:
        logger.error("metrics_generation_failed", error=str(e))
        return Response(
            content="# Error generating metrics\n", media_type=CONTENT_TYPE_LATEST, status_code=500
        )
