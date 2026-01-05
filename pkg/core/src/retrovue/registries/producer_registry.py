"""
Producer Registry for CLI contract compliance.

This module provides access to the producer registry from the adapters module.
It serves as a bridge between the CLI commands and the adapter registry.
"""

from __future__ import annotations

from typing import Any

from ..adapters.registry import (
    UnsupportedProducer,
    get_producer_help as _get_producer_help,
    list_producers as _list_producers,
)


def list_producer_types() -> list[dict[str, str]]:
    """
    List all available producer types.

    Returns:
        List of dictionaries with 'type' and 'description' keys
    """
    producer_names = _list_producers()

    # Get descriptions from help info
    result = []
    for producer_type in producer_names:
        try:
            help_info = _get_producer_help(producer_type)
            description = help_info.get("description", f"{producer_type} producer")
            result.append({"type": producer_type, "description": description})
        except UnsupportedProducer:
            # Fallback if help can't be retrieved
            result.append({"type": producer_type, "description": f"{producer_type} producer"})

    return result


def get_producer_help(producer_type: str) -> dict[str, Any]:
    """
    Get help information for a specific producer type.

    Args:
        producer_type: The producer type name

    Returns:
        Dictionary with help information (description, required_params, optional_params, examples)

    Raises:
        UnsupportedProducer: If the producer type is not found
    """
    try:
        return _get_producer_help(producer_type)
    except UnsupportedProducer:
        # Return minimal help info for unknown types
        return {
            "description": f"Unknown producer type: {producer_type}",
            "required_params": [],
            "optional_params": [],
            "examples": [],
        }
