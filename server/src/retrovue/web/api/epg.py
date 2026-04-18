"""
EPG (Electronic Program Guide) API.

Reads from canonical DB-cached schedule (ScheduleRevision/ScheduleItems)
and returns program block metadata as JSON.

INV-EPG-READS-CANONICAL-SCHEDULE-001: EPG endpoints MUST read from the
canonical compiled schedule. They MUST NOT call compile_schedule() directly.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from retrovue.epg.read_path import build_epg_payload, resolve_epg_broadcast_day
from retrovue.runtime.clock import SystemClock
from retrovue.runtime.catalog_resolver import CatalogAssetResolver
from retrovue.infra.uow import session

router = APIRouter(prefix="/api", tags=["epg"])

YAML_CHANNELS_DIR = __import__("pathlib").Path("/opt/retrovue/config/channels")
_clock = SystemClock()


def _load_channels() -> list[dict[str, Any]]:
    from retrovue.runtime.providers import YamlChannelConfigProvider
    from retrovue.config import load_defaults
    if YAML_CHANNELS_DIR.is_dir():
        return YamlChannelConfigProvider(YAML_CHANNELS_DIR, resolved_config=load_defaults()).to_channels_list()
    return []


@router.get("/epg")
def get_epg(
    date: str = Query(default=None, description="Date in YYYY-MM-DD format"),
    channel: str = Query(default=None, description="Channel ID filter"),
):
    """Return EPG data for all (or one) channel on a given date.

    INV-EPG-READS-CANONICAL-SCHEDULE-001: reads from canonical relational
    schedule data via DslScheduleService.get_canonical_epg().
    """
    channels = _load_channels()
    if channel:
        channels = [c for c in channels if c["channel_id"] == channel]

    broadcast_day = resolve_epg_broadcast_day(
        channels,
        date,
        now_utc=_clock.now_utc(),
    )

    with session() as db:
        shared_resolver = CatalogAssetResolver(db)

    payload = build_epg_payload(channels, broadcast_day, shared_resolver)
    return JSONResponse(content=payload)
