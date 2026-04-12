"""
Path mapping workflow per INV-PATH-MAPPING-SOURCE-SCOPED-001.

Source-level path mappings use canonical fields source_path / retrovue_path.
Containers inherit source mappings automatically; container-level overrides
take precedence per-prefix.

This module MUST NOT read from stdin or write to stdout.
"""

from __future__ import annotations

from typing import Any

# Provider-specific field names that MUST be rejected
_FORBIDDEN_FIELDS = frozenset({"plex_path", "local_path"})

# Canonical field names
_REQUIRED_FIELDS = frozenset({"source_path", "retrovue_path"})


def validate_mapping_fields(mapping: dict[str, Any]) -> None:
    """Validate that a path mapping dict uses canonical field names.

    Raises ValueError with INV-PATH-MAPPING-SOURCE-SCOPED-001-VIOLATED
    if provider-specific field names are present.
    """
    forbidden_present = _FORBIDDEN_FIELDS & set(mapping.keys())
    if forbidden_present:
        raise ValueError(
            "INV-PATH-MAPPING-SOURCE-SCOPED-001-VIOLATED: "
            f"provider-specific field names not allowed: {sorted(forbidden_present)}. "
            f"Use canonical fields: source_path, retrovue_path"
        )


def resolve_effective_mappings(
    *,
    source: Any,
    container: Any,
) -> list[tuple[str, str]]:
    """Compute effective path mappings for a container.

    Source-level mappings are inherited by default. Container-level overrides
    take precedence for their specific source_path prefix.

    Args:
        source: Object with .path_mappings list of objects having
            .source_path and .retrovue_path attributes.
        container: Object with .path_mappings list (may be empty).

    Returns:
        List of (source_path, retrovue_path) tuples representing the
        effective mappings for this container.
    """
    # Start with source-level mappings
    effective: dict[str, str] = {}
    for m in getattr(source, "path_mappings", []):
        effective[m.source_path] = m.retrovue_path

    # Container-level overrides take precedence per-prefix
    for m in getattr(container, "path_mappings", []):
        effective[m.source_path] = m.retrovue_path

    return [(k, v) for k, v in effective.items()]
