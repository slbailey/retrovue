"""
Enricher domain entity for RetroVue.

Represents a configured enricher instance with type, configuration, and metadata.
"""

import hashlib
import time
from dataclasses import dataclass
from typing import Any


@dataclass
class Enricher:
    """
    Domain entity representing a configured enricher instance.

    Attributes:
        id: Unique identifier in format "enricher-{type}-{hash}"
        type: Enricher type identifier (e.g., "ffprobe", "metadata")
        scope: Enricher scope ("ingest" or "playout")
        name: Human-readable name for the enricher
        config: Configuration dictionary specific to the enricher type
        created_at: Timestamp when the enricher was created
    """

    id: str
    type: str
    scope: str
    name: str
    config: dict[str, Any]
    created_at: str | None = None

    def __post_init__(self) -> None:
        """Validate enricher data after initialization."""
        if not self.id.startswith(f"enricher-{self.type}-"):
            raise ValueError(f"Invalid enricher ID format: {self.id}")

        if self.scope not in ["ingest", "playout"]:
            raise ValueError(f"Invalid scope: {self.scope}. Must be 'ingest' or 'playout'")

        if not self.name.strip():
            raise ValueError("Enricher name cannot be empty")

    @classmethod
    def create(
        cls,
        enricher_type: str,
        name: str,
        config: dict[str, Any] | None = None,
        scope: str | None = None,
    ) -> "Enricher":
        """
        Create a new enricher instance with generated ID.

        Args:
            enricher_type: Type of enricher (e.g., "ffprobe")
            name: Human-readable name
            config: Configuration dictionary
            scope: Enricher scope (auto-detected if not provided)

        Returns:
            New Enricher instance
        """
        # Generate unique ID with timestamp to avoid collisions
        timestamp = int(time.time())
        id_hash = hashlib.md5(f"{enricher_type}-{name}-{timestamp}".encode()).hexdigest()[:8]
        enricher_id = f"enricher-{enricher_type}-{id_hash}"

        # Auto-detect scope if not provided
        if scope is None:
            scope = cls._detect_scope(enricher_type)

        # Set default config if not provided
        if config is None:
            config = cls._get_default_config(enricher_type)

        return cls(id=enricher_id, type=enricher_type, scope=scope, name=name, config=config)

    @staticmethod
    def _detect_scope(enricher_type: str) -> str:
        """Detect the scope based on enricher type."""
        # For now, assume all enrichers are ingest-scoped by default
        # In the future, this could be more sophisticated based on the actual enricher type
        return "ingest"

    @staticmethod
    def _get_default_config(enricher_type: str) -> dict[str, Any]:
        """Get default configuration for an enricher type."""
        defaults: dict[str, dict[str, Any]] = {"ingest": {}, "playout": {}}
        return defaults.get(enricher_type, {})

    def to_dict(self) -> dict[str, Any]:
        """Convert enricher to dictionary for JSON serialization."""
        return {
            "enricher_id": self.id,
            "type": self.type,
            "scope": self.scope,
            "name": self.name,
            "config": self.config,
            "status": "created",
        }

    def validate_config(self) -> None:
        """Validate the enricher configuration against its scope schema."""
        if self.scope == "ingest":
            self._validate_ingest_config()
        elif self.scope == "playout":
            self._validate_playout_config()
        else:
            raise ValueError(f"Unknown enricher scope: {self.scope}")

    def _validate_ingest_config(self) -> None:
        """Validate ingest enricher configuration."""
        # Ingest enrichers can have any configuration
        # Specific validation would be done by the actual enricher implementation
        if not isinstance(self.config, dict):
            raise ValueError("Configuration must be a dictionary")

    def _validate_playout_config(self) -> None:
        """Validate playout enricher configuration."""
        # Playout enrichers can have any configuration
        # Specific validation would be done by the actual enricher implementation
        if not isinstance(self.config, dict):
            raise ValueError("Configuration must be a dictionary")
