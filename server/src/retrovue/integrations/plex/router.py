"""
Plex HDHomeRun virtual tuner — FastAPI router.

Mounts HDHomeRun-compatible HTTP endpoints onto an existing FastAPI app.
All logic delegates to PlexAdapter (service layer).

Endpoints:
  GET /discover.json      — INV-PLEX-DISCOVERY-001
  GET /lineup.json        — INV-PLEX-LINEUP-001
  GET /lineup_status.json — INV-PLEX-TUNER-STATUS-001
  GET /epg.xml            — INV-PLEX-XMLTV-001
"""

from __future__ import annotations

from fastapi import APIRouter, Request, Response

from retrovue.integrations.plex.service import PlexAdapter


def create_plex_router(adapter: PlexAdapter) -> APIRouter:
    """Build a FastAPI router wired to the given PlexAdapter.

    Mount with: app.include_router(create_plex_router(adapter))

    Stream endpoints are not included here — Plex streams use the
    existing /channel/{id}.ts endpoint directly via lineup URL.
    """
    router = APIRouter(tags=["plex"])

    @router.get("/discover.json")
    def discover(request: Request):
        """HDHomeRun device discovery — INV-PLEX-DISCOVERY-001."""
        return adapter.discover()

    @router.get("/lineup.json")
    def lineup(request: Request):
        """HDHomeRun channel lineup — INV-PLEX-LINEUP-001."""
        return adapter.lineup()

    @router.get("/lineup_status.json")
    def lineup_status(request: Request):
        """Tuner scan status — INV-PLEX-TUNER-STATUS-001."""
        return adapter.lineup_status()

    @router.get("/epg.xml")
    def epg_xml(request: Request):
        """XMLTV guide data — INV-PLEX-XMLTV-001.

        Delegates to generate_xmltv() via PlexAdapter.epg_xml().
        """
        return Response(
            content=adapter.epg_xml(),
            media_type="application/xml",
        )

    return router
