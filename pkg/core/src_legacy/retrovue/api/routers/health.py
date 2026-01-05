"""
Health check endpoints for Retrovue.

This module provides health check endpoints for monitoring and load balancer health checks.
"""

from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from ...infra.logging import get_logger
from ...infra.uow import get_db

router = APIRouter()
logger = get_logger(__name__)


@router.get("/healthz")
async def health_check(db: Session = Depends(get_db)) -> dict[str, Any]:
    """
    Health check endpoint.

    Returns:
        Dict containing status, version, and database connectivity status
    """
    start_time = time.time()

    try:
        # Perform lightweight database check
        db.execute(text("SELECT 1"))
        db_status = "ok"
        db_error = None
    except Exception as e:
        db_status = "error"
        db_error = str(e)
        logger.error("health_check_db_error", error=str(e))

    response_time = (time.time() - start_time) * 1000  # Convert to milliseconds

    response = {
        "status": "ok" if db_status == "ok" else "error",
        "version": "0.1.0",  # TODO: Get from package version
        "db": db_status,
        "response_time_ms": round(response_time, 2),
        "timestamp": time.time(),
    }

    if db_error:
        response["db_error"] = db_error

    # Log the health check
    logger.info(
        "health_check",
        status=response["status"],
        db_status=db_status,
        response_time_ms=response_time,
    )

    # Return 503 if database is not healthy
    if db_status != "ok":
        raise HTTPException(status_code=503, detail=response)

    return response
