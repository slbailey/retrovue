"""Configuration module for Retrovue.

Public API:
    resolve_channel_config  — merge defaults + channel YAML → frozen config
    resolve_defaults_only   — frozen defaults (no channel overrides)
    load_defaults           — load and cache config/defaults.yaml
    get_defaults            — convenience wrapper for load_defaults()
"""

from retrovue.config.config_loader import get_defaults, load_defaults
from retrovue.config.resolver import resolve_channel_config, resolve_defaults_only

__all__ = [
    "get_defaults",
    "load_defaults",
    "resolve_channel_config",
    "resolve_defaults_only",
]
