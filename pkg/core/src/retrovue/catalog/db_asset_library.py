"""
DatabaseAssetLibrary — satisfies the AssetLibrary protocol using the
RetroVue database for asset lookups, including channel-aware interstitial
selection with cooldown enforcement for traffic management.

Policy (what's allowed) comes from YAML channel configs.
State (what has aired) lives in the database.

Usage:
    from retrovue.catalog.db_asset_library import DatabaseAssetLibrary
    lib = DatabaseAssetLibrary(db, channel_slug="retro-prime")
    fillers = lib.get_filler_assets(max_duration_ms=120000, count=10)
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import func
from sqlalchemy.orm import Session

from retrovue.runtime.planning_pipeline import FillerAsset, MarkerInfo


# Default traffic policy when no YAML config exists
DEFAULT_TRAFFIC_POLICY: dict[str, Any] = {
    "allowed_types": ["commercial", "promo", "station_id", "psa",
                       "stinger", "bumper", "filler"],
    "default_cooldown_seconds": 3600,
    "type_cooldowns": {},
    "max_plays_per_day": 0,
}

# Where channel YAML configs live
CHANNEL_CONFIG_DIR = Path("/opt/retrovue/config/channels")


def _load_channel_traffic_policy(
    channel_slug: str,
    config_dir: Path = CHANNEL_CONFIG_DIR,
) -> dict[str, Any]:
    """Load traffic policy from channel YAML config.

    Uses the same !include-aware loader as the rest of RetroVue.
    Falls back to _defaults.yaml, then hardcoded defaults.
    """
    from retrovue.runtime.providers.yaml_channel_config_provider import (
        _load_yaml_with_includes,
    )

    policy = dict(DEFAULT_TRAFFIC_POLICY)

    # Try loading defaults first
    defaults_path = config_dir / "_defaults.yaml"
    if defaults_path.exists():
        defaults = _load_yaml_with_includes(defaults_path)
        if "traffic" in defaults:
            policy.update(defaults["traffic"])

    # Then overlay channel-specific config
    channel_path = config_dir / f"{channel_slug}.yaml"
    if channel_path.exists():
        channel_cfg = _load_yaml_with_includes(channel_path)
        if "traffic" in channel_cfg:
            policy.update(channel_cfg["traffic"])

    return policy


class DatabaseAssetLibrary:
    """AssetLibrary backed by the RetroVue database.

    Policy: from YAML channel configs (human-editable)
    State: from DB traffic_play_log (machine-tracked)
    """

    def __init__(
        self,
        db: Session,
        channel_slug: str | None = None,
        interstitial_collection_name: str = "Interstitials",
        config_dir: Path | str | None = None,
    ) -> None:
        self._db = db
        self._channel_slug = channel_slug
        self._interstitial_collection_name = interstitial_collection_name
        self._config_dir = Path(config_dir) if config_dir else CHANNEL_CONFIG_DIR
        self._interstitial_collection_uuid: str | None = None
        self._policy: dict | None = None

    def _get_interstitial_collection_uuid(self) -> str | None:
        if self._interstitial_collection_uuid is not None:
            return self._interstitial_collection_uuid

        from retrovue.domain.entities import Collection
        coll = self._db.query(Collection).filter(
            Collection.name == self._interstitial_collection_name
        ).first()
        if coll:
            self._interstitial_collection_uuid = str(coll.uuid)
        return self._interstitial_collection_uuid

    def _get_channel_policy(self) -> dict[str, Any]:
        """Load traffic policy from YAML. Cached for session lifetime."""
        if self._policy is not None:
            return self._policy

        if self._channel_slug:
            self._policy = _load_channel_traffic_policy(
                self._channel_slug, self._config_dir
            )
        else:
            self._policy = dict(DEFAULT_TRAFFIC_POLICY)

        return self._policy

    def _get_cooled_down_uris(self) -> set[str]:
        """Get asset URIs still in cooldown on this channel (from DB)."""
        if not self._channel_slug:
            return set()

        from retrovue.domain.entities import TrafficPlayLog

        policy = self._get_channel_policy()
        max_cooldown = max(
            policy.get("default_cooldown_seconds", 3600),
            max((policy.get("type_cooldowns") or {}).values(), default=0),
        )
        if max_cooldown <= 0:
            return set()

        cutoff = datetime.now(timezone.utc) - timedelta(seconds=max_cooldown)

        recent_plays = self._db.query(
            TrafficPlayLog.asset_uri,
            TrafficPlayLog.asset_type,
            TrafficPlayLog.played_at,
        ).filter(
            TrafficPlayLog.channel_slug == self._channel_slug,
            TrafficPlayLog.played_at >= cutoff,
        ).all()

        cooled = set()
        now = datetime.now(timezone.utc)
        type_cooldowns = policy.get("type_cooldowns") or {}
        default_cd = policy.get("default_cooldown_seconds", 3600)

        for uri, asset_type, played_at in recent_plays:
            cooldown_secs = type_cooldowns.get(asset_type, default_cd)
            if (now - played_at).total_seconds() < cooldown_secs:
                cooled.add(uri)

        return cooled

    def _get_daily_capped_uuids(self) -> set[str]:
        """Get asset UUIDs that hit their daily play cap on this channel."""
        if not self._channel_slug:
            return set()

        policy = self._get_channel_policy()
        cap = policy.get("max_plays_per_day", 0)
        if cap <= 0:
            return set()

        from retrovue.domain.entities import TrafficPlayLog

        today_start = datetime.now(timezone.utc).replace(
            hour=0, minute=0, second=0, microsecond=0
        )

        capped = self._db.query(
            TrafficPlayLog.asset_uuid,
        ).filter(
            TrafficPlayLog.channel_slug == self._channel_slug,
            TrafficPlayLog.played_at >= today_start,
        ).group_by(
            TrafficPlayLog.asset_uuid,
        ).having(
            func.count(TrafficPlayLog.id) >= cap,
        ).all()

        return {str(row[0]) for row in capped}

    # ── AssetLibrary protocol ──

    def get_duration_ms(self, asset_uri: str) -> int:
        from retrovue.domain.entities import Asset
        asset = self._db.query(Asset).filter(
            Asset.canonical_uri == asset_uri
        ).first()
        if not asset:
            asset = self._db.query(Asset).filter(Asset.uri == asset_uri).first()
        return asset.duration_ms if asset and asset.duration_ms else 0

    def get_markers(self, asset_uri: str) -> list[MarkerInfo]:
        from retrovue.domain.entities import Asset, Marker
        asset = self._db.query(Asset).filter(
            Asset.canonical_uri == asset_uri
        ).first()
        if not asset:
            return []
        markers = self._db.query(Marker).filter(
            Marker.asset_uuid == asset.uuid
        ).order_by(Marker.start_ms).all()
        return [
            MarkerInfo(
                kind=m.kind.value if hasattr(m.kind, 'value') else str(m.kind),
                offset_ms=m.start_ms,
                label=(m.payload or {}).get("title", ""),
            )
            for m in markers
        ]

    def get_filler_assets(
        self, max_duration_ms: int, count: int = 1
    ) -> list[FillerAsset]:
        """Get interstitial assets respecting channel policy and cooldowns.

        Policy from YAML, cooldown state from DB.
        """
        coll_uuid = self._get_interstitial_collection_uuid()
        if not coll_uuid:
            return []

        from retrovue.domain.entities import Asset, AssetEditorial

        policy = self._get_channel_policy()
        allowed_types = set(policy.get("allowed_types", []))
        cooled_uris = self._get_cooled_down_uris()
        capped_uuids = self._get_daily_capped_uuids()

        rows = (
            self._db.query(
                Asset.uuid,
                Asset.canonical_uri,
                Asset.duration_ms,
                AssetEditorial.payload,
            )
            .outerjoin(AssetEditorial, Asset.uuid == AssetEditorial.asset_uuid)
            .filter(
                Asset.collection_uuid == coll_uuid,
                Asset.state == "ready",
                Asset.duration_ms.isnot(None),
                Asset.duration_ms > 0,
                Asset.duration_ms <= max_duration_ms,
            )
            .all()
        )

        if not rows:
            return []

        candidates = []
        for asset_uuid, uri, duration_ms, payload in rows:
            editorial = payload or {}
            interstitial_type = editorial.get("interstitial_type", "filler")

            if interstitial_type not in allowed_types:
                continue
            if uri in cooled_uris:
                continue
            if str(asset_uuid) in capped_uuids:
                continue

            candidates.append(FillerAsset(
                asset_uri=uri,
                duration_ms=duration_ms,
                asset_type=interstitial_type,
            ))

        random.shuffle(candidates)
        return candidates[:count]

    def log_play(
        self,
        asset_uri: str,
        asset_uuid: UUID | str,
        asset_type: str,
        duration_ms: int,
        break_index: int | None = None,
        block_id: str | None = None,
        played_at: datetime | None = None,
    ) -> None:
        """Record an interstitial play for cooldown tracking (writes to DB)."""
        if not self._channel_slug:
            return

        from retrovue.domain.entities import TrafficPlayLog

        log = TrafficPlayLog(
            channel_slug=self._channel_slug,
            asset_uuid=UUID(asset_uuid) if isinstance(asset_uuid, str) else asset_uuid,
            asset_uri=asset_uri,
            asset_type=asset_type,
            played_at=played_at or datetime.now(timezone.utc),
            break_index=break_index,
            block_id=block_id,
            duration_ms=duration_ms,
        )
        self._db.add(log)
