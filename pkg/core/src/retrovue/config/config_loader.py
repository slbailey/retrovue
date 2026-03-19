"""
Load and cache global defaults from config/defaults.yaml.

INV-CONFIG-IMMUTABLE-001: The loaded defaults are frozen after first load.
Environment variable overrides are applied as transforms to the defaults
layer BEFORE any channel merge occurs.
"""

from __future__ import annotations

import logging
import os
import threading
from pathlib import Path
from types import MappingProxyType
from typing import Any

import yaml

logger = logging.getLogger(__name__)

# Module-level singleton: loaded once, read many.
_defaults: MappingProxyType[str, Any] | None = None
_defaults_lock = threading.Lock()

# Top-level domains defined in defaults.yaml (governs unknown-key rejection).
GOVERNED_DOMAINS: frozenset[str] = frozenset({
    "scheduling",
    "playout",
    "channel",
    "hls",
    "streaming",
    "system",
    "integrations",
    "air",
})

# Search order for defaults.yaml.
_SEARCH_PATHS: tuple[Path, ...] = (
    Path("config/defaults.yaml"),
    Path("/opt/retrovue/config/defaults.yaml"),
)

# Environment variable overrides.
# Each entry maps an env var name to a (dotted_path, cast_fn) pair.
# These are applied to the mutable defaults dict before freezing.
_ENV_OVERRIDES: tuple[tuple[str, str, type], ...] = (
    ("RETROVUE_MIN_PREFEED_LEAD_TIME_MS", "playout.timing.min_prefeed_lead_time_ms", int),
    ("HTTP_CLIENT_BUFFER_BYTES", "streaming.buffers.client_buffer_bytes", int),
    ("HTTP_RING_BUFFER_BYTES", "streaming.buffers.ring_buffer_max_bytes", int),
)


def _set_nested(d: dict[str, Any], dotted_key: str, value: Any) -> None:
    """Set a value in a nested dict using a dotted key path."""
    keys = dotted_key.split(".")
    for key in keys[:-1]:
        d = d.setdefault(key, {})
    d[keys[-1]] = value


def _apply_env_overrides(defaults: dict[str, Any]) -> None:
    """Apply environment variable overrides to the mutable defaults dict."""
    for env_var, dotted_path, cast_fn in _ENV_OVERRIDES:
        raw = os.environ.get(env_var)
        if raw is not None:
            try:
                _set_nested(defaults, dotted_path, cast_fn(raw))
                logger.info("Config override: %s=%s (from %s)", dotted_path, raw, env_var)
            except (ValueError, TypeError) as exc:
                logger.warning(
                    "Ignoring invalid env override %s=%r: %s", env_var, raw, exc,
                )


def _deep_freeze(obj: Any) -> Any:
    """Recursively freeze a nested dict/list structure.

    - dict -> MappingProxyType (read-only view)
    - list -> tuple (immutable sequence)
    - scalars pass through unchanged
    """
    if isinstance(obj, dict):
        return MappingProxyType({k: _deep_freeze(v) for k, v in obj.items()})
    if isinstance(obj, list):
        return tuple(_deep_freeze(item) for item in obj)
    return obj


def load_defaults(path: str | Path | None = None) -> MappingProxyType[str, Any]:
    """Load, validate, and return the frozen global defaults.

    Thread-safe singleton: the first call loads from disk; subsequent calls
    return the cached frozen object.  Schema validation always runs — it
    cannot be bypassed through this function.  Tests that need intentionally
    incomplete YAML fixtures should use ``retrovue.config.testing``
    helpers instead.

    Args:
        path: Explicit path to defaults.yaml.  When None, searches the
              standard locations.

    Returns:
        Deeply frozen MappingProxyType of the defaults tree.

    Raises:
        FileNotFoundError: If no defaults.yaml can be found.
        yaml.YAMLError: If the file is not valid YAML.
        SchemaValidationError: If schema validation fails.
    """
    return _load_defaults_impl(path, _validate=True)


def _load_defaults_impl(
    path: str | Path | None,
    *,
    _validate: bool,
) -> MappingProxyType[str, Any]:
    """Internal implementation shared by public loader and test helper.

    _validate is an internal flag — NOT exposed through load_defaults().
    The only caller with _validate=False is the test helper in
    retrovue.config.testing.
    """
    global _defaults

    if _defaults is not None:
        return _defaults

    with _defaults_lock:
        if _defaults is not None:
            return _defaults

        resolved_path = _resolve_path(path)
        raw = resolved_path.read_text(encoding="utf-8")
        data = yaml.safe_load(raw)

        if not isinstance(data, dict):
            raise ValueError(
                f"defaults.yaml must be a YAML mapping, got {type(data).__name__}"
            )

        _apply_env_overrides(data)

        if _validate:
            from retrovue.config.schema import validate_defaults
            validate_defaults(data)

        _defaults = _deep_freeze(data)
        logger.info("Global defaults loaded from %s", resolved_path)
        return _defaults


def _resolve_path(path: str | Path | None) -> Path:
    """Resolve the defaults.yaml path using the search order."""
    if path is not None:
        p = Path(path)
        if p.exists():
            return p
        raise FileNotFoundError(f"Explicit defaults path does not exist: {p}")

    for candidate in _SEARCH_PATHS:
        if candidate.exists():
            return candidate

    raise FileNotFoundError(
        f"config/defaults.yaml not found in search paths: {_SEARCH_PATHS}"
    )


def reset_defaults_cache() -> None:
    """Reset the cached defaults (for testing only)."""
    global _defaults
    with _defaults_lock:
        _defaults = None


def get_defaults() -> MappingProxyType[str, Any]:
    """Return the cached defaults, loading if necessary.

    Convenience wrapper around load_defaults() for callers that don't
    need to specify a path.
    """
    return load_defaults()


__all__ = [
    "GOVERNED_DOMAINS",
    "load_defaults",
    "get_defaults",
    "reset_defaults_cache",
    "_deep_freeze",
]
