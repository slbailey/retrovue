"""
Configuration resolver — public API.

Combines global defaults with per-channel overrides to produce a fully
resolved, immutable configuration object.

Contract: docs/contracts/configuration_resolution.md

INV-CONFIG-IMMUTABLE-001: Resolved config is frozen after creation.
INV-CONFIG-IDENTITY-001: Stable identity within a channel activation.
"""

from __future__ import annotations

import logging
from pathlib import Path
from types import MappingProxyType
from typing import Any

import yaml

from retrovue.config.config_loader import (
    GOVERNED_DOMAINS,
    _deep_freeze,
    load_defaults,
)
from retrovue.config.merge import deep_merge

logger = logging.getLogger(__name__)

# Channel-specific domain keys (not governed by defaults.yaml).
# These pass through the merge without validation.
CHANNEL_DOMAIN_KEYS: frozenset[str] = frozenset({
    "channel_id",
    "number",
    "name",
    "channel_type",
    "timezone",
    "format",
    "pools",
    "programs",
    "schedule",
    "traffic",
})


def resolve_channel_config(
    channel_path: str | Path,
    *,
    defaults_path: str | Path | None = None,
) -> MappingProxyType[str, Any]:
    """Load a channel YAML and merge it with global defaults.

    Returns a deeply frozen MappingProxyType — the resolved configuration
    for one channel.  No key from defaults.yaml will be missing.

    Args:
        channel_path: Path to the channel's YAML file.
        defaults_path: Optional explicit path to defaults.yaml
            (primarily for testing).

    Returns:
        Frozen resolved configuration.

    Raises:
        FileNotFoundError: If the channel YAML does not exist.
        yaml.YAMLError: If the channel YAML is invalid.
        ConfigMergeError: If merge validation fails
            (unknown keys, type mismatches, structural conflicts).
    """
    defaults = load_defaults(defaults_path)

    channel_data = _load_channel_yaml(channel_path)

    # Schema validation: fail fast on structural/identifier errors.
    from retrovue.config.schema import validate_channel_yaml
    validate_channel_yaml(channel_data)

    # Partition channel data into governed overrides and pass-through keys.
    governed_overrides: dict[str, Any] = {}
    passthrough: dict[str, Any] = {}

    for key, value in channel_data.items():
        if key in GOVERNED_DOMAINS and isinstance(value, dict):
            governed_overrides[key] = value
        else:
            # Pass-through: channel identifiers (channel: "hbo"),
            # channel-specific domain data (pools, programs, schedule, traffic),
            # and scalar uses of governed-domain names (e.g., channel: "hbo"
            # where defaults has channel: {dict}).
            passthrough[key] = value

    # Merge governed overrides into defaults (validates types, structure, unknown keys).
    merged = deep_merge(
        defaults,
        governed_overrides,
        governed_keys=GOVERNED_DOMAINS,
    )

    # Attach pass-through keys (channel-specific domain data).
    # Special case: when a passthrough key name collides with a governed domain
    # (e.g., `channel: "hbo"` identifier vs the governed `channel:` dict),
    # the scalar identifier is stored under `channel_id` and the governed dict
    # is preserved at its domain key.
    for key, value in passthrough.items():
        if key in GOVERNED_DOMAINS and key in merged:
            # Collision: governed domain already populated from defaults merge.
            # Preserve the identifier under `{key}_id`.
            merged[f"{key}_id"] = value
        else:
            merged[key] = value

    frozen = _deep_freeze(merged)
    logger.info(
        "Resolved config for channel '%s' from %s",
        channel_data.get("channel", "?"),
        channel_path,
    )
    return frozen


def resolve_defaults_only(
    *,
    defaults_path: str | Path | None = None,
) -> MappingProxyType[str, Any]:
    """Return global defaults as the resolved config (no channel overrides).

    Used when no channel YAML exists or for system-level configuration.
    """
    return load_defaults(defaults_path)


def _load_channel_yaml(path: str | Path) -> dict[str, Any]:
    """Load and validate the basic structure of a channel YAML file."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Channel configuration not found: {p}")

    raw = p.read_text(encoding="utf-8")
    data = yaml.safe_load(raw)

    if not isinstance(data, dict):
        raise ValueError(
            f"Channel YAML must be a mapping, got {type(data).__name__}: {p}"
        )

    return data


__all__ = [
    "resolve_channel_config",
    "resolve_defaults_only",
    "CHANNEL_DOMAIN_KEYS",
]
