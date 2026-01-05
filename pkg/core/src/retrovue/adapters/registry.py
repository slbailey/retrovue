"""
Plugin registry for importers, enrichers, producers, and renderers.

This module is the plug-in registry for Importers, Enrichers, Producers, and Renderers, not business logic.
It maintains global registries for all available importers, enrichers, producers, and renderers.
Plugins self-register when imported, allowing for a modular architecture.
"""

from __future__ import annotations

from typing import Any

from .enrichers.base import Enricher, EnricherConfig, EnricherNotFoundError
from .enrichers.ffprobe_enricher import FFprobeEnricher
from .importers.base import DiscoveredItem, Importer, ImporterNotFoundError
from .importers.filesystem_importer import FilesystemImporter
from .importers.plex_importer import PlexImporter
from .producers.base import BaseProducer, ProducerNotFoundError as ProducerNotFoundErrorBase
from .producers.file_producer import FileProducer
from .producers.test_pattern_producer import TestPatternProducer
from .renderers.base import BaseRenderer, RendererNotFoundError as RendererNotFoundErrorBase
from .renderers.ffmpeg_ts_renderer import FFmpegTSRenderer

# Global registries
_importers: dict[str, Importer] = {}
_enrichers: dict[str, Enricher] = {}
_producers: dict[str, type[BaseProducer]] = {}
_renderers: dict[str, type[BaseRenderer]] = {}

# Importer aliases for better user experience
ALIASES = {
    "fs": "filesystem",
    "filesystem": "filesystem",
    "plex": "plex",
    "plexapi": "plex",
}

# Available importer classes
SOURCES = {
    "filesystem": FilesystemImporter,
    "fs": FilesystemImporter,  # alias
    "plex": PlexImporter,
}

# Available enricher classes
ENRICHERS = {
    "ffprobe": FFprobeEnricher,
}

# Available producer classes
PRODUCERS = {
    "file": FileProducer,
    "test-pattern": TestPatternProducer,
}

# Producer aliases for better user experience
PRODUCER_ALIASES = {
    "file": "file",
    "test": "test-pattern",
    "testpattern": "test-pattern",
    "pattern": "test-pattern",
}

# Available renderer classes
RENDERERS = {
    "ffmpeg-ts": FFmpegTSRenderer,
}

# Renderer aliases for better user experience
RENDERER_ALIASES = {
    "ffmpeg-ts": "ffmpeg-ts",
    "ts": "ffmpeg-ts",
    "mpegts": "ffmpeg-ts",
    "mpeg-ts": "ffmpeg-ts",
}


class UnsupportedSource(ValueError):
    """Raised when an unsupported source is requested."""

    pass


def register_importer(importer: Importer) -> None:
    """
    Register an importer with the global registry.

    Args:
        importer: The importer to register

    Raises:
        ValueError: If importer name is empty or already registered
    """
    if not importer.name:
        raise ValueError("Importer name cannot be empty")

    if importer.name in _importers:
        raise ValueError(f"Importer '{importer.name}' is already registered")

    _importers[importer.name] = importer


def get_importer(name: str, **kwargs: Any) -> Importer:
    """
    Get an importer by name.

    Args:
        name: The name of the importer
        **kwargs: Additional arguments to pass to the importer constructor

    Returns:
        The requested importer instance

    Raises:
        UnsupportedSource: If the importer is not found
    """
    key = ALIASES.get(name.lower(), name.lower())
    try:
        cls = SOURCES[key]
    except KeyError:
        raise UnsupportedSource(
            f"Unsupported source: {name}. Available: {', '.join(sorted(SOURCES.keys()))}"
        ) from None
    return cls(**kwargs)  # type: ignore[no-any-return]


def get_importer_help(name: str) -> dict[str, Any]:
    """
    Get help information for an importer without creating an instance.

    Args:
        name: The importer name

    Returns:
        Help information dictionary

    Raises:
        UnsupportedSource: If the importer is not found
    """
    key = ALIASES.get(name.lower(), name.lower())
    try:
        cls = SOURCES[key]
    except KeyError:
        raise UnsupportedSource(
            f"Unsupported source: {name}. Available: {', '.join(sorted(SOURCES.keys()))}"
        ) from None

    # Create a minimal instance to get help (with minimal required parameters)
    try:
        # Try to create with minimal parameters
        if key == "filesystem":
            instance = cls(source_name="help", root_paths=["."])
        elif key == "plex":
            instance = cls(base_url="http://localhost:32400", token="dummy")
        else:
            instance = cls()

        return instance.get_help()  # type: ignore[no-any-return]
    except Exception:
        # If we can't create an instance, return basic help
        return {
            "description": f"Importer for {key} sources",
            "required_params": [],
            "optional_params": [],
            "examples": [f"retrovue source add --type {key} --name 'My {key.title()} Source'"],
            "cli_params": {},
        }


def list_importers() -> list[str]:
    """
    List all available importer names.

    Returns:
        List of all available importer names
    """
    return list(SOURCES.keys())


def unregister_importer(name: str) -> None:
    """
    Unregister an importer.

    Args:
        name: The name of the importer to unregister

    Raises:
        ImporterNotFoundError: If the importer is not found
    """
    if name not in _importers:
        raise ImporterNotFoundError(f"Importer '{name}' not found")

    del _importers[name]


def register_enricher(enricher: Enricher) -> None:
    """
    Register an enricher with the global registry.

    Args:
        enricher: The enricher to register

    Raises:
        ValueError: If enricher name is empty or already registered
    """
    if not enricher.name:
        raise ValueError("Enricher name cannot be empty")

    if enricher.name in _enrichers:
        raise ValueError(f"Enricher '{enricher.name}' is already registered")

    _enrichers[enricher.name] = enricher


def get_enricher(name: str) -> Enricher:
    """
    Get an enricher by name.

    Args:
        name: The name of the enricher

    Returns:
        The requested enricher

    Raises:
        EnricherNotFoundError: If the enricher is not found
    """
    if name not in _enrichers:
        raise EnricherNotFoundError(f"Enricher '{name}' not found")

    return _enrichers[name]


def list_enrichers() -> list[Enricher]:
    """
    List all registered enrichers.

    Returns:
        List of all registered enrichers
    """
    # Return enricher instances from the ENRICHERS dictionary
    enricher_instances: list[Enricher] = []
    for name, enricher_class in ENRICHERS.items():
        try:
            # Create an instance of the enricher
            instance = enricher_class()
            enricher_instances.append(instance)
        except Exception:
            # If we can't create an instance, create a mock enricher with just the name
            class MockEnricher(Enricher):
                def __init__(self, name: str) -> None:
                    self.name = name
                    self.config: dict[str, Any] = {}
                    self.scope = "ingest"

                def enrich(self, discovered_item: DiscoveredItem) -> DiscoveredItem:
                    return discovered_item

                @classmethod
                def get_config_schema(cls) -> EnricherConfig:
                    return EnricherConfig(
                        required_params=[],
                        optional_params=[],
                        scope="ingest",
                        description="Mock enricher for testing",
                    )

            enricher_instances.append(MockEnricher(name))
    return enricher_instances


def unregister_enricher(name: str) -> None:
    """
    Unregister an enricher.

    Args:
        name: The name of the enricher to unregister

    Raises:
        EnricherNotFoundError: If the enricher is not found
    """
    if name not in _enrichers:
        raise EnricherNotFoundError(f"Enricher '{name}' not found")

    del _enrichers[name]


def clear_registries() -> None:
    """
    Clear all registered importers, enrichers, producers, and renderers.

    This is primarily useful for testing.
    """
    global _importers, _enrichers, _producers, _renderers
    _importers.clear()
    _enrichers.clear()
    _producers.clear()
    _renderers.clear()


def _register_builtin_enrichers() -> None:
    """Register built-in enrichers."""
    # Note: Enrichers need to be instantiated with their required parameters
    # For now, we'll register them as classes and let the CLI handle instantiation
    pass


# Register built-in enrichers on module import
_register_builtin_enrichers()


def get_registry_stats() -> dict[str, Any]:
    """
    Get statistics about the registry.

    Returns:
        Dictionary with registry statistics
    """
    return {
        "importers": {"count": len(_importers), "names": list(_importers.keys())},
        "enrichers": {"count": len(_enrichers), "names": list(_enrichers.keys())},
        "producers": {"count": len(_producers), "names": list(_producers.keys())},
        "renderers": {"count": len(_renderers), "names": list(_renderers.keys())},
    }


# Producer registry functions

class UnsupportedProducer(ValueError):
    """Raised when an unsupported producer is requested."""

    pass


def register_producer(producer_class: type[BaseProducer]) -> None:
    """
    Register a producer class with the global registry.

    Args:
        producer_class: The producer class to register

    Raises:
        ValueError: If producer name is empty or already registered
    """
    if not hasattr(producer_class, "name") or not producer_class.name:
        raise ValueError("Producer class must have a 'name' attribute")

    if producer_class.name in _producers:
        raise ValueError(f"Producer '{producer_class.name}' is already registered")

    _producers[producer_class.name] = producer_class


def get_producer(name: str, **kwargs: Any) -> BaseProducer:
    """
    Get a producer instance by name.

    Args:
        name: The name of the producer
        **kwargs: Additional arguments to pass to the producer constructor

    Returns:
        The requested producer instance

    Raises:
        UnsupportedProducer: If the producer is not found
    """
    key = PRODUCER_ALIASES.get(name.lower(), name.lower())
    try:
        cls = PRODUCERS[key]
    except KeyError:
        raise UnsupportedProducer(
            f"Unsupported producer: {name}. Available: {', '.join(sorted(PRODUCERS.keys()))}"
        ) from None
    return cls(**kwargs)  # type: ignore[no-any-return]


def get_producer_help(name: str) -> dict[str, Any]:
    """
    Get help information for a producer without creating an instance.

    Args:
        name: The producer name

    Returns:
        Help information dictionary

    Raises:
        UnsupportedProducer: If the producer is not found
    """
    key = PRODUCER_ALIASES.get(name.lower(), name.lower())
    try:
        cls = PRODUCERS[key]
    except KeyError:
        raise UnsupportedProducer(
            f"Unsupported producer: {name}. Available: {', '.join(sorted(PRODUCERS.keys()))}"
        ) from None

    # Create a minimal instance to get help (with minimal required parameters)
    try:
        schema = cls.get_config_schema()
        # Try to create with minimal parameters
        if key == "file":
            instance = cls(file_path="/tmp/dummy.mp4")
        elif key == "test-pattern":
            instance = cls()
        else:
            # For other producers, try with empty config
            instance = cls()

        return instance.get_help()  # type: ignore[no-any-return]
    except Exception:
        # If we can't create an instance, return basic help from schema
        schema = cls.get_config_schema()
        return {
            "description": schema.description,
            "required_params": schema.required_params,
            "optional_params": schema.optional_params,
            "examples": [f"retrovue producer add --type {key} --name 'My {key.title()} Producer'"],
            "cli_params": {},
        }


def list_producers() -> list[str]:
    """
    List all available producer names.

    Returns:
        List of all available producer names
    """
    return list(PRODUCERS.keys())


def unregister_producer(name: str) -> None:
    """
    Unregister a producer.

    Args:
        name: The name of the producer to unregister

    Raises:
        ProducerNotFoundErrorBase: If the producer is not found
    """
    if name not in _producers:
        raise ProducerNotFoundErrorBase(f"Producer '{name}' not found")

    del _producers[name]


# Register built-in producers on module import
for producer_class in PRODUCERS.values():
    register_producer(producer_class)


# Renderer registry functions

class UnsupportedRenderer(ValueError):
    """Raised when an unsupported renderer is requested."""

    pass


def register_renderer(renderer_class: type[BaseRenderer]) -> None:
    """
    Register a renderer class with the global registry.

    Args:
        renderer_class: The renderer class to register

    Raises:
        ValueError: If renderer name is empty or already registered
    """
    if not hasattr(renderer_class, "name") or not renderer_class.name:
        raise ValueError("Renderer class must have a 'name' attribute")

    if renderer_class.name in _renderers:
        raise ValueError(f"Renderer '{renderer_class.name}' is already registered")

    _renderers[renderer_class.name] = renderer_class


def get_renderer(name: str, **kwargs: Any) -> BaseRenderer:
    """
    Get a renderer instance by name.

    Args:
        name: The name of the renderer
        **kwargs: Additional arguments to pass to the renderer constructor

    Returns:
        The requested renderer instance

    Raises:
        UnsupportedRenderer: If the renderer is not found
    """
    key = RENDERER_ALIASES.get(name.lower(), name.lower())
    try:
        cls = RENDERERS[key]
    except KeyError:
        raise UnsupportedRenderer(
            f"Unsupported renderer: {name}. Available: {', '.join(sorted(RENDERERS.keys()))}"
        ) from None
    return cls(**kwargs)  # type: ignore[no-any-return]


def get_renderer_help(name: str) -> dict[str, Any]:
    """
    Get help information for a renderer without creating an instance.

    Args:
        name: The renderer name

    Returns:
        Help information dictionary

    Raises:
        UnsupportedRenderer: If the renderer is not found
    """
    key = RENDERER_ALIASES.get(name.lower(), name.lower())
    try:
        cls = RENDERERS[key]
    except KeyError:
        raise UnsupportedRenderer(
            f"Unsupported renderer: {name}. Available: {', '.join(sorted(RENDERERS.keys()))}"
        ) from None

    # Create a minimal instance to get help (with minimal required parameters)
    try:
        schema = cls.get_config_schema()
        # Try to create with minimal parameters
        if key == "ffmpeg-ts":
            instance = cls()
        else:
            # For other renderers, try with empty config
            instance = cls()

        return instance.get_help()  # type: ignore[no-any-return]
    except Exception:
        # If we can't create an instance, return basic help from schema
        schema = cls.get_config_schema()
        return {
            "description": schema.description,
            "required_params": schema.required_params,
            "optional_params": schema.optional_params,
            "examples": [f"retrovue renderer add --type {key} --name 'My {key.title()} Renderer'"],
            "cli_params": {},
        }


def list_renderers() -> list[str]:
    """
    List all available renderer names.

    Returns:
        List of all available renderer names
    """
    return list(RENDERERS.keys())


def unregister_renderer(name: str) -> None:
    """
    Unregister a renderer.

    Args:
        name: The name of the renderer to unregister

    Raises:
        RendererNotFoundErrorBase: If the renderer is not found
    """
    if name not in _renderers:
        raise RendererNotFoundErrorBase(f"Renderer '{name}' not found")

    del _renderers[name]


# Register built-in renderers on module import
for renderer_class in RENDERERS.values():
    register_renderer(renderer_class)
