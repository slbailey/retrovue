# RetroVue API Reference

_Related: [Developer: Plugin authoring](PluginAuthoring.md) • [Developer: Registry API](RegistryAPI.md) • [Developer: Testing plugins](TestingPlugins.md)_

This document provides a comprehensive API reference for extending RetroVue with custom importers and enrichers.

## Importer API

### Base Importer Protocol

```python
from typing import Protocol
from dataclasses import dataclass
from datetime import datetime

@dataclass
class DiscoveredItem:
    """Standard format for discovered content items."""
    path_uri: str                      # URI to the content
    provider_key: str | None = None    # Provider-specific identifier
    raw_labels: list[str] | None = None  # Extracted metadata labels
    last_modified: datetime | None = None  # Last modification time
    size: int | None = None            # File size in bytes

class Importer(Protocol):
    """Protocol that all importers must implement."""
    name: str

    def discover(self) -> list[DiscoveredItem]:
        """Discover content items from the source."""
        ...
```

### Required Implementation

All importers must implement:

1. **`name`**: String identifier for the importer type
2. **`discover()`**: Method that returns a list of `DiscoveredItem` objects

### Example Implementation

```python
class CustomImporter:
    name = "custom"

    def __init__(self, **kwargs):
        # Store configuration
        pass

    def discover(self) -> list[DiscoveredItem]:
        # Implementation
        pass
```

## Enricher API

### Base Enricher Protocol

```python
from typing import Protocol
from ..importers.base import DiscoveredItem

class Enricher(Protocol):
    """Protocol that all enrichers must implement."""
    name: str

    def enrich(self, discovered_item: DiscoveredItem) -> DiscoveredItem:
        """Enrich a discovered item with additional metadata."""
        ...
```

### Required Implementation

All enrichers must implement:

1. **`name`**: String identifier for the enricher type
2. **`enrich()`**: Method that takes a `DiscoveredItem` and returns an enriched version

### Example Implementation

```python
class CustomEnricher:
    name = "custom"

    def __init__(self, **kwargs):
        # Store configuration
        pass

    def enrich(self, discovered_item: DiscoveredItem) -> DiscoveredItem:
        # Implementation
        pass
```

## Registry API

### Importer Registration

```python
from retrovue.adapters.registry import SOURCES

# Register a new importer
SOURCES["custom"] = CustomImporter
```

### Enricher Registration

```python
from retrovue.adapters.registry import register_enricher

# Register a new enricher
register_enricher(CustomEnricher())
```

### Available Registry Functions

```python
# List available importers
from retrovue.adapters.registry import list_importers
importers = list_importers()

# List available enrichers
from retrovue.adapters.registry import list_enrichers
enrichers = list_enrichers()

# Get an importer instance
from retrovue.adapters.registry import get_importer
importer = get_importer("plex", server_url="...", token="...")

# Get an enricher instance
from retrovue.adapters.registry import get_enricher
enricher = get_enricher("ffprobe")
```

## Built-in Importers

### Filesystem Importer

**Type**: `filesystem` or `fs`

**Parameters**:

- `source_name` (str): Human-readable name for the source
- `root_paths` (list[str]): List of directories to scan
- `glob_patterns` (list[str], optional): File patterns to match
- `include_hidden` (bool, optional): Include hidden files
  

**Example**:

```python
importer = FilesystemImporter(
    source_name="My Media Library",
    root_paths=["/media/movies", "/media/tv"],
    glob_patterns=["**/*.mp4", "**/*.mkv"],
    include_hidden=False
)
```

### Plex Importer

**Type**: `plex`

**Parameters**:

- `servers` (list[dict]): List of server configurations
  - `base_url` (str): Plex server URL
  - `token` (str): Plex authentication token
- `include_metadata` (bool, optional): Include Plex metadata

**Example**:

```python
importer = PlexImporter(
    servers=[
        {
            "base_url": "http://plex:32400",
            "token": "your-plex-token"
        }
    ],
    include_metadata=True
)
```

### Custom Media Server Importer

**Type**: `custom_media_server` (example)

**Parameters**:

- `servers` (list[dict]): List of server configurations
  - `base_url` (str): Media server URL
  - `api_key` (str): API key
  - `user_id` (str): User ID
- `include_metadata` (bool, optional): Include server metadata

**Example**:

```python
importer = CustomMediaServerImporter(
    servers=[
        {
            "base_url": "http://server:8096",
            "api_key": "your-api-key",
            "user_id": "user123"
        }
    ],
    include_metadata=True
)
```

## Built-in Enrichers

### FFprobe Enricher

**Type**: `ffprobe`

**Parameters**:

- `ffprobe_path` (str, optional): Path to FFprobe executable

**Example**:

```python
enricher = FFprobeEnricher(ffprobe_path="ffprobe")
```

### Custom Metadata API Enricher

**Type**: `custom_metadata_api` (example)

**Parameters**:

- `api_key` (str): API key for the metadata service
- `base_url` (str, optional): API base URL

**Example**:

```python
enricher = CustomMetadataAPIEnricher(
    api_key="your-api-key",
    base_url="https://api.example.com"
)
```

## CLI Integration

### Source Management Commands

```bash
# List available source types and enrichers
retrovue source list-types

# Add a source
retrovue source add --type <importer_type> --name <name> [options]

# List configured sources
retrovue source list

# List collections from sources
retrovue source collections
```

### Source Type Parameters

#### Filesystem Sources

```bash
retrovue source add --type filesystem \
  --name "My Media Library" \
  --base-path "/media/movies"
```

#### Plex Sources

```bash
retrovue source add --type plex \
  --name "My Plex Server" \
  --base-url "http://plex:32400" \
  --token "your-plex-token"
```

#### Jellyfin Sources

```bash
retrovue source add --type jellyfin \
  --name "My Jellyfin Server" \
  --base-url "http://jellyfin:8096" \
  --api-key "your-api-key" \
  --user-id "user123"
```

#### Sources with Enrichers

```bash
retrovue source add --type plex \
  --name "Plex Server" \
  --base-url "http://plex:32400" \
  --token "token" \
  --enrichers "ffprobe,tvdb"
```

## Error Handling

### Importer Errors

```python
from retrovue.adapters.importers.base import ImporterError, ImporterNotFoundError, ImporterConfigurationError

# Raise specific errors
raise ImporterError("General importer error")
raise ImporterNotFoundError("Importer not found")
raise ImporterConfigurationError("Invalid configuration")
```

### Enricher Errors

```python
from retrovue.adapters.enrichers.base import EnricherError, EnricherNotFoundError, EnricherConfigurationError

# Raise specific errors
raise EnricherError("General enricher error")
raise EnricherNotFoundError("Enricher not found")
raise EnricherConfigurationError("Invalid configuration")
```

## Testing

### Unit Testing Importers

```python
import pytest
from unittest.mock import Mock, patch
from retrovue.adapters.importers.custom_importer import CustomImporter

class TestCustomImporter:
    def test_discover_basic(self):
        """Test basic discovery functionality."""
        with patch('external_api.get_items') as mock_get:
            mock_get.return_value = [{"id": "123", "title": "Test"}]

            importer = CustomImporter(api_key="test")
            items = importer.discover()

            assert len(items) == 1
            assert items[0].provider_key == "123"
```

### Unit Testing Enrichers

```python
import pytest
from retrovue.adapters.enrichers.custom_enricher import CustomEnricher
from retrovue.adapters.importers.base import DiscoveredItem

class TestCustomEnricher:
    def test_enrich_basic(self):
        """Test basic enrichment functionality."""
        enricher = CustomEnricher(api_key="test")

        item = DiscoveredItem(
            path_uri="file:///test.mp4",
            raw_labels=["title:Test Movie"]
        )

        enriched = enricher.enrich(item)

        assert len(enriched.raw_labels) > len(item.raw_labels)
        assert any("custom_metadata:" in label for label in enriched.raw_labels)
```

## Best Practices

### 1. Configuration Validation

```python
def validate_config(config: dict) -> None:
    """Validate importer/enricher configuration."""
    required_fields = ['api_key', 'base_url']

    for field in required_fields:
        if field not in config:
            raise ImporterConfigurationError(f"Missing required field: {field}")
```

### 2. Resource Management

```python
class ResourceImporter:
    """Importer that properly manages resources."""

    def __init__(self, config: dict):
        self.config = config
        self.session = None

    def discover(self) -> list[DiscoveredItem]:
        """Discover with proper resource management."""
        try:
            self.session = self._create_session()
            return self._do_discovery()
        finally:
            self._cleanup_resources()

    def _cleanup_resources(self):
        """Clean up resources."""
        if self.session:
            self.session.close()
```

### 3. Error Handling

```python
def discover_with_retry(importer: Importer, max_retries: int = 3) -> list[DiscoveredItem]:
    """Discover content with retry logic."""
    for attempt in range(max_retries):
        try:
            return importer.discover()
        except ImporterConnectionError as e:
            if attempt == max_retries - 1:
                raise
            print(f"Connection failed, retrying in 5 seconds... ({attempt + 1}/{max_retries})")
            time.sleep(5)
        except ImporterError as e:
            print(f"Importer error: {e}")
            raise
        except Exception as e:
            print(f"Unexpected error: {e}")
            raise
```

### 4. Logging

```python
import logging
from retrovue.infra.logging import get_logger

class LoggingImporter:
    """Importer with comprehensive logging."""

    def __init__(self, config: dict):
        self.logger = get_logger(__name__)
        self.config = config

    def discover(self) -> list[DiscoveredItem]:
        """Discover with detailed logging."""
        self.logger.info("Starting content discovery", importer=self.name)

        try:
            items = self._do_discovery()
            self.logger.info("Discovery completed", item_count=len(items))
            return items
        except Exception as e:
            self.logger.error("Discovery failed", error=str(e))
            raise
```

---

_This API reference provides comprehensive information for extending RetroVue. For more examples, see the existing importers and enrichers in the source code._
