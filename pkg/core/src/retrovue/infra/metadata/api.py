"""
Internal Metadata API Router

This router exposes developer-facing endpoints for metadata validation and testing.
It is NOT the production ingest endpoint; real importer traffic enters through
CollectionIngestService.ingest_collection(), which calls handle_ingest() directly.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from retrovue.usecases.metadata_handler import handle_ingest

from .schema_loader import load_sidecar_validator

router = APIRouter()


@router.get("/metadata/schema/sidecar", response_model=dict)
def get_sidecar_schema() -> dict:
    """Return the current RetroVue sidecar JSON Schema.a

    Useful for importer services or QA tools to fetch the authoritative schema.
    """
    try:
        validator = load_sidecar_validator()
        return dict(validator.schema)
    except Exception as exc:  # pragma: no cover
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/metadata/test-ingest", response_model=dict)
async def ingest_metadata(request: Request) -> dict:
    """Receive importer payloads and delegate to the usecase handler.

    Flow:
    1) Read request JSON into a plain dict (payload)
    2) Call usecase handle_ingest(payload)
    3) On ValueError (validation), return 400 with the message
    4) Otherwise return 200 with the result
    """
    try:
        payload = await request.json()
        result = handle_ingest(payload)
        return result
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as exc:  # pragma: no cover
        raise HTTPException(status_code=500, detail=str(exc))


