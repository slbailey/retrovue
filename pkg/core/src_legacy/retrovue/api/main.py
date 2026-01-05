"""
FastAPI main application for Retrovue admin GUI.

This module provides the main FastAPI application with web routes for the admin interface.
"""

from __future__ import annotations

import os
import time
import uuid
from collections.abc import Callable

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

# Ensure registry is populated
import retrovue.adapters.importers  # noqa: F401

from ..infra.settings import settings
from .routers import assets, health, ingest, metrics, review
from .web import pages

# Create FastAPI app
app = FastAPI(
    title="Retrovue Admin",
    description="Admin interface for Retrovue content management",
    version="1.0.0",
)

# Add CORS middleware with configurable origins
allowed_origins = settings.allowed_origins.split(",") if settings.allowed_origins != "*" else ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Add request ID middleware
@app.middleware("http")
async def request_id_middleware(request: Request, call_next: Callable) -> Response:
    """Middleware to generate request IDs and log request/response details."""
    # Generate unique request ID
    request_id = str(uuid.uuid4())

    # Store request ID in request state for use in endpoints
    request.state.request_id = request_id

    # Get logger with proper configuration
    from ..infra.logging import get_logger

    logger = get_logger("request")

    # Log request start
    start_time = time.time()
    logger = logger.bind(request_id=request_id)
    logger.info(
        "request_started",
        method=request.method,
        path=request.url.path,
        query_params=str(request.query_params) if request.query_params else None,
        client_ip=request.client.host if request.client else None,
    )

    # Process request
    try:
        response = await call_next(request)

        # Calculate processing time
        process_time = time.time() - start_time

        # Log request completion
        logger.info(
            "request_completed",
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            process_time_ms=round(process_time * 1000, 2),
        )

        # Add request ID to response headers
        response.headers["X-Request-ID"] = request_id

        return response

    except Exception as e:
        # Calculate processing time
        process_time = time.time() - start_time

        # Log request error
        logger.error(
            "request_failed",
            method=request.method,
            path=request.url.path,
            error=str(e),
            process_time_ms=round(process_time * 1000, 2),
        )

        # Re-raise the exception
        raise


# Mount static files (if directory exists)
if os.path.exists("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")

# Setup Jinja2 templates
templates = Jinja2Templates(directory="src/retrovue/api/web/templates")

# Note: Database schema is managed by Alembic migrations
# Do NOT call Base.metadata.create_all() in production

# Include API routers
app.include_router(assets.router)
app.include_router(ingest.router, prefix="/api")
app.include_router(review.router, prefix="/api")
app.include_router(health.router, prefix="/api")
app.include_router(metrics.router, prefix="/api")

# Include web routes
app.include_router(pages.router)


@app.get("/health", tags=["health"])
async def health_redirect():
    """Legacy health endpoint - redirects to new healthz endpoint."""
    from fastapi.responses import RedirectResponse

    return RedirectResponse(url="/api/healthz")


@app.get("/")
async def root():
    """Root endpoint redirects to dashboard."""
    from fastapi.responses import RedirectResponse

    return RedirectResponse(url="/dashboard")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
