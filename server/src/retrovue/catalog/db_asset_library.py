"""
DatabaseAssetLibrary — satisfies the AssetLibrary protocol using the
RetroVue database for asset lookups, including channel-aware interstitial
selection with cooldown enforcement for traffic management.

Policy (what's allowed) comes from YAML channel configs.
State (what has aired) lives in the database.

Usage:
    from retrovue.catalog.db_asset_library import DatabaseAssetLibrary
    from retrovue.runtime.clock import SystemClock
    lib = DatabaseAssetLibrary(db, clock=SystemClock(), channel_slug="retro-prime")
    fillers = lib.get_filler_assets(max_duration_ms=120000, count=10)
"""

from __future__ import annotations

import logging
import random
import warnings
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..runtime.clock import AuthoritativeClock

logger = logging.getLogger(__name__)


@dataclass
class MarkerInfo:
    """Lightweight marker data (no SQLAlchemy dependency)."""
    kind: str           # e.g. "chapter"
    offset_ms: int      # Offset from asset start in milliseconds
    label: str = ""


@dataclass
class FillerAsset:
    """Filler item resolved from AssetLibrary."""
    asset_uri: str
    duration_ms: int
    asset_type: str = "filler"   # "filler", "promo", "ad"
    asset_category: str | None = None
    cooldown_group: str | None = None
    tags: tuple[str, ...] = ()


# Default traffic policy when no YAML config exists
DEFAULT_TRAFFIC_POLICY: dict[str, Any] = {
    "allowed_types": ["commercial", "promo", "station_id", "psa",
                       "stinger", "bumper", "filler"],
    "default_cooldown_seconds": 3600,
    "type_cooldowns_seconds": {},
    "max_plays_per_day": 0,
}

# Where channel YAML configs live
CHANNEL_CONFIG_DIR = Path("/opt/retrovue/config/channels")


def _load_channel_traffic_policy(
    channel_slug: str,
    config_dir: Path = CHANNEL_CONFIG_DIR,
) -> dict[str, Any]:
    """Load traffic policy from channel YAML config.

    Resolves the channel's default traffic profile and returns a flat
    policy dict with allowed_types, cooldowns, and caps from that profile.

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
            _apply_traffic_config(policy, defaults["traffic"])

    # Then overlay channel-specific config
    channel_path = config_dir / f"{channel_slug}.yaml"
    if channel_path.exists():
        channel_cfg = _load_yaml_with_includes(channel_path)
        if "traffic" in channel_cfg:
            _apply_traffic_config(
                policy,
                channel_cfg["traffic"],
                pools=channel_cfg.get("pools"),
            )

    return policy


def _apply_traffic_config(
    policy: dict[str, Any],
    traffic: dict[str, Any],
    pools: dict[str, Any] | None = None,
) -> None:
    """Resolve a traffic section into a flat policy dict.

    Reads the default profile from traffic.profiles and extracts its
    fields into the policy dict.

    When the profile declares allowed_pools, the pool definitions are
    stored in the policy so get_filler_assets() can evaluate them
    directly against asset metadata — preserving full pool query semantics
    (type, tags, and any future criteria).

    allowed_types is a legacy fallback only — allowed_pools takes precedence.
    """
    profiles = traffic.get("profiles", {})
    default_name = traffic.get("default_profile")

    if default_name and default_name in profiles:
        profile = profiles[default_name]
        # allowed_types: DEPRECATED legacy type-based filtering.
        # Use allowed_pools instead. allowed_types will be removed in a future version.
        if "allowed_types" in profile:
            warnings.warn(
                f"Traffic profile '{default_name}' uses deprecated 'allowed_types'. "
                f"Migrate to 'allowed_pools' referencing named pool definitions.",
                DeprecationWarning,
                stacklevel=3,
            )
            policy["allowed_types"] = profile["allowed_types"]
        # allowed_pools: pool-based filtering (takes precedence over allowed_types)
        if "allowed_pools" in profile:
            pool_names = profile["allowed_pools"]
            pool_defs = {}
            missing = []
            if pools:
                for name in pool_names:
                    if name in pools:
                        pool_defs[name] = pools[name]
                    else:
                        missing.append(name)
            else:
                missing = list(pool_names)
            if missing:
                raise ValueError(
                    f"Traffic profile '{default_name}' references undefined pools: "
                    f"{missing}. Each allowed_pool must be defined in the channel's "
                    f"pools section."
                )
            policy["allowed_pools"] = pool_names
            policy["pool_definitions"] = pool_defs
        if "default_cooldown_seconds" in profile:
            policy["default_cooldown_seconds"] = profile["default_cooldown_seconds"]
        if "type_cooldowns_seconds" in profile:
            policy["type_cooldowns_seconds"] = profile["type_cooldowns_seconds"]
        if "max_plays_per_day" in profile:
            policy["max_plays_per_day"] = profile["max_plays_per_day"]


def _asset_matches_pool(editorial: dict[str, Any], pool_def: dict[str, Any]) -> bool:
    """Check if an asset's editorial metadata matches a pool's query.

    Evaluates select.where (new DSL) or match (legacy) criteria against
    the asset's editorial payload. All criteria are AND-combined.
    """
    where = pool_def.get("select", {}).get("where", {})
    if not where:
        where = pool_def.get("match", {})
    if not where:
        # Empty pool definition = no criteria = matches nothing.
        # An empty pool is a configuration error, not a wildcard.
        return False

    interstitial_type = editorial.get("interstitial_type", "")
    tags = set(editorial.get("tags", []))

    for field, clause in where.items():
        if isinstance(clause, dict):
            # Operator-based: {eq: val}, {in: [...]}, {contains_all: [...]}
            if "eq" in clause:
                actual = interstitial_type if field == "type" else editorial.get(field)
                if actual != clause["eq"]:
                    return False
            if "in" in clause:
                actual = interstitial_type if field == "type" else editorial.get(field)
                if actual not in clause["in"]:
                    return False
            if "contains_all" in clause:
                if field == "tags":
                    from retrovue.domain.tag_normalization import expand_tag_match_set
                    expanded = expand_tag_match_set(tags)
                    if not set(clause["contains_all"]).issubset(expanded):
                        return False
            if "contains_any" in clause:
                if field == "tags":
                    from retrovue.domain.tag_normalization import expand_tag_match_set
                    expanded = expand_tag_match_set(tags)
                    if not set(clause["contains_any"]).intersection(expanded):
                        return False
            if "excludes_any" in clause:
                if field == "tags":
                    from retrovue.domain.tag_normalization import expand_tag_match_set
                    if set(clause["excludes_any"]).intersection(expand_tag_match_set(tags)):
                        return False
        else:
            # Legacy flat value: {type: "trailer"} or {tags: [a, b]}
            if field == "type":
                if interstitial_type != clause:
                    return False
            elif field == "tags":
                required = set(clause) if isinstance(clause, list) else {clause}
                if not required.issubset(tags):
                    return False
            else:
                if editorial.get(field) != clause:
                    return False

    return True


class DatabaseAssetLibrary:
    """AssetLibrary backed by the RetroVue database.

    Policy: from YAML channel configs (human-editable)
    State: from DB traffic_play_log (machine-tracked)
    """

    def __init__(
        self,
        db: Session,
        *,
        clock: AuthoritativeClock,
        channel_slug: str | None = None,
        interstitial_collection_name: str = "Interstitials",
        config_dir: Path | str | None = None,
    ) -> None:
        self._db = db
        self._clock = clock
        self._channel_slug = channel_slug
        self._interstitial_collection_name = interstitial_collection_name
        self._config_dir = Path(config_dir) if config_dir else CHANNEL_CONFIG_DIR
        self._interstitial_collection_uuid: str | None = None
        self._policy: dict | None = None

    def _get_interstitial_collection_uuid(self) -> str | None:
        if self._interstitial_collection_uuid is not None:
            return self._interstitial_collection_uuid

        from retrovue.domain.entities import Container
        coll = self._db.query(Container).filter(
            Container.name == self._interstitial_collection_name
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

    def _get_cooled_down_uris(self) -> tuple[set[str], set[str]]:
        """Get asset URIs and cooldown groups still in cooldown (from DB).

        Returns (cooled_uris, cooled_groups) so callers can exclude both
        individual assets and all members of a cooled group.
        """
        if not self._channel_slug:
            return set(), set()

        from retrovue.domain.entities import TrafficPlayLog

        policy = self._get_channel_policy()
        max_cooldown = max(
            policy.get("default_cooldown_seconds", 3600),
            max((policy.get("type_cooldowns_seconds") or {}).values(), default=0),
        )
        if max_cooldown <= 0:
            return set(), set()

        cutoff = self._clock.now_utc() - timedelta(seconds=max_cooldown)

        recent_plays = self._db.query(
            TrafficPlayLog.asset_uri,
            TrafficPlayLog.asset_type,
            TrafficPlayLog.played_at,
            TrafficPlayLog.cooldown_group,
        ).filter(
            TrafficPlayLog.channel_slug == self._channel_slug,
            TrafficPlayLog.played_at >= cutoff,
        ).all()

        cooled_uris: set[str] = set()
        cooled_groups: set[str] = set()
        now = self._clock.now_utc()
        type_cooldowns = policy.get("type_cooldowns_seconds") or {}
        default_cd = policy.get("default_cooldown_seconds", 3600)

        for uri, asset_type, played_at, group in recent_plays:
            cooldown_secs = type_cooldowns.get(asset_type, default_cd)
            if (now - played_at).total_seconds() < cooldown_secs:
                if group:
                    cooled_groups.add(group)
                else:
                    cooled_uris.add(uri)

        return cooled_uris, cooled_groups

    def _get_daily_capped_uuids(self) -> set[str]:
        """Get asset UUIDs that hit their daily play cap on this channel."""
        if not self._channel_slug:
            return set()

        policy = self._get_channel_policy()
        cap = policy.get("max_plays_per_day", 0)
        if cap <= 0:
            return set()

        from retrovue.domain.entities import TrafficPlayLog

        today_start = self._clock.now_utc().replace(
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

        When the policy contains allowed_pools (with pool_definitions),
        each asset is matched against the pool queries — preserving full
        DSL semantics (type, tags, and any future criteria).

        When only allowed_types is present (legacy), filters by
        editorial.interstitial_type.

        Policy from YAML, cooldown state from DB.
        """
        from retrovue.domain.entities import Asset, AssetEditorial

        policy = self._get_channel_policy()
        pool_defs = policy.get("pool_definitions", {})
        use_pools = bool(pool_defs)
        allowed_types = set(policy.get("allowed_types", []))
        cooled_uris, cooled_groups = self._get_cooled_down_uris()
        capped_uuids = self._get_daily_capped_uuids()

        # Query all assets that have interstitial_type stamped in editorial.
        rows = (
            self._db.query(
                Asset.uuid,
                Asset.canonical_uri,
                Asset.duration_ms,
                AssetEditorial.payload,
            )
            .join(AssetEditorial, Asset.uuid == AssetEditorial.asset_uuid)
            .filter(
                Asset.state == "ready",
                Asset.duration_ms.isnot(None),
                Asset.duration_ms > 0,
                Asset.duration_ms <= max_duration_ms,
                AssetEditorial.payload.has_key("interstitial_type"),
            )
            .all()
        )

        if not rows:
            return []

        # Batch-load tags from asset_tags table for pool matching.
        # Editorial JSONB may not carry tags (they live in asset_tags).
        from retrovue.domain.entities import AssetTag
        asset_uuids = [r[0] for r in rows]
        tag_rows = (
            self._db.query(AssetTag.asset_uuid, AssetTag.tag)
            .filter(AssetTag.asset_uuid.in_(asset_uuids))
            .all()
        )
        tags_by_uuid: dict[str, set[str]] = {}
        for t_uuid, t_tag in tag_rows:
            tags_by_uuid.setdefault(str(t_uuid), set()).add(t_tag)

        candidates = []
        for asset_uuid, uri, duration_ms, payload in rows:
            editorial = payload or {}
            interstitial_type = editorial.get("interstitial_type")
            cooldown_group = editorial.get("cooldown_group")

            # Merge DB tags into editorial for pool matching.
            asset_tags = tags_by_uuid.get(str(asset_uuid), set())
            editorial_for_match = dict(editorial)
            if asset_tags:
                editorial_for_match["tags"] = list(asset_tags)

            # INV-TRAFFIC-POOL-UNION-001: Candidate set is the union of
            # all allowed_pools. An asset is eligible if ANY pool matches.
            if use_pools:
                matched_pools = [
                    pname for pname, pdef in pool_defs.items()
                    if _asset_matches_pool(editorial_for_match, pdef)
                ]
                if not matched_pools:
                    continue
                logger.debug(
                    "traffic_candidate: %s type=%s matched_pools=%s",
                    uri[-40:], interstitial_type, matched_pools,
                )
            else:
                # DEPRECATED: allowed_types fallback. Migrate to allowed_pools.
                if interstitial_type not in allowed_types:
                    continue

            # Cooldown and cap filtering
            if cooldown_group and cooldown_group in cooled_groups:
                continue
            if not cooldown_group and uri in cooled_uris:
                continue
            if str(asset_uuid) in capped_uuids:
                continue

            candidates.append(FillerAsset(
                asset_uri=uri,
                duration_ms=duration_ms,
                asset_type=interstitial_type,
                asset_category=editorial.get("interstitial_category"),
                cooldown_group=editorial.get("cooldown_group"),
                tags=tuple(sorted(asset_tags)),
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
        cooldown_group: str | None = None,
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
            played_at=played_at or self._clock.now_utc(),
            break_index=break_index,
            block_id=block_id,
            duration_ms=duration_ms,
            cooldown_group=cooldown_group,
        )
        self._db.add(log)
