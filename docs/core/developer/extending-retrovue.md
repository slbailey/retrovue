_Related: [Plugin authoring](PluginAuthoring.md) • [Registry API](RegistryAPI.md) • [Testing plugins](TestingPlugins.md)_

# Extending RetroVue

This guide explains how to extend RetroVue with custom importers and enrichers using the modular adapter system.

## Overview

RetroVue uses a plugin-based architecture where:

- **Importers** discover content from various sources (Plex, filesystem, Jellyfin, etc.)
- **Enrichers** add metadata to discovered content (FFprobe, TVDB, etc.)
- **Registry** manages available importers and enrichers

## Architecture

### Core Components

1. **Importer Protocol** (`src/retrovue/adapters/importers/base.py`)

   - Defines the interface all importers must implement
   - Returns standardized `DiscoveredItem` objects

2. **Enricher Protocol** (`src/retrovue/adapters/enrichers/base.py`)

   - Defines the interface all enrichers must implement
   - Takes `DiscoveredItem` and returns enriched version

3. **Registry System** (`src/retrovue/adapters/registry.py`)
   - Manages available importers and enrichers
   - Provides factory methods for creating instances

## Creating Custom Importers

### 1. Basic Importer Structure

```python
from typing import Protocol
from ..base import DiscoveredItem, Importer, ImporterError

class CustomImporter:
    """Custom importer for your specific source."""

    name = "custom"  # This is the importer type identifier

    def __init__(self, **kwargs):
        """Initialize with configuration."""
        # Store configuration parameters
        pass

    def discover(self) -> list[DiscoveredItem]:
        """Discover content from your source."""
        try:
            discovered_items = []

            # Your discovery logic here
            for item in self._scan_source():
                discovered_item = self._create_discovered_item(item)
                if discovered_item:
                    discovered_items.append(discovered_item)

            return discovered_items

        except Exception as e:
            raise ImporterError(f"Discovery failed: {str(e)}") from e

    def _scan_source(self):
        """Scan your content source."""
        # Implementation specific to your source
        pass

    def _create_discovered_item(self, item) -> DiscoveredItem | None:
        """Convert source item to DiscoveredItem."""
        try:
            return DiscoveredItem(
                path_uri=self._get_uri(item),
                provider_key=self._get_provider_key(item),
                raw_labels=self._extract_labels(item),
                last_modified=self._get_modified_time(item),
                size=self._get_size(item),
                hash_sha256=self._calculate_hash(item)
            )
        except Exception as e:
            print(f"Warning: Failed to process item {item}: {e}")
            return None
```

### 2. Media Server Importer Example

```python
import requests
from typing import Any
from ..base import DiscoveredItem, Importer, ImporterError

class MediaServerImporter:
    """Example importer for a media server (Jellyfin, Emby, etc.)."""

    name = "media_server"

    def __init__(self, server_url: str, api_key: str, user_id: str):
        self.server_url = server_url.rstrip('/')
        self.api_key = api_key
        self.user_id = user_id
        self.session = requests.Session()
        self.session.headers.update({
            'X-Emby-Token': api_key,
            'Content-Type': 'application/json'
        })

    def discover(self) -> list[DiscoveredItem]:
        """Discover content from media server."""
        try:
            # Get all items from the server
            items = self._get_server_items()
            discovered_items = []

            for item in items:
                discovered_item = self._create_discovered_item(item)
                if discovered_item:
                    discovered_items.append(discovered_item)

            return discovered_items

        except Exception as e:
            raise ImporterError(f"Media server discovery failed: {str(e)}") from e

    def _get_server_items(self) -> list[dict[str, Any]]:
        """Fetch items from media server API."""
        url = f"{self.server_url}/Users/{self.user_id}/Items"
        params = {
            'Recursive': 'true',
            'IncludeItemTypes': 'Movie,Episode',
            'Fields': 'Path,DateCreated,MediaSources'
        }

        response = self.session.get(url, params=params)
        response.raise_for_status()

        return response.json().get('Items', [])

    def _create_discovered_item(self, item: dict[str, Any]) -> DiscoveredItem | None:
        """Convert server item to DiscoveredItem."""
        try:
            # Extract file path from media sources
            media_sources = item.get('MediaSources', [])
            if not media_sources:
                return None

            file_path = media_sources[0].get('Path', '')
            if not file_path:
                return None

            # Create URI
            path_uri = f"mediaserver://{self.server_url}/item/{item['Id']}"

            # Extract labels from tags and genres
            labels = []
            labels.extend(item.get('Tags', []))
            labels.extend(item.get('Genres', []))

            return DiscoveredItem(
                path_uri=path_uri,
                provider_key=item['Id'],
                raw_labels=labels,
                last_modified=self._parse_date(item.get('DateCreated')),
                size=media_sources[0].get('Size', 0),
                hash_sha256=None  # Server doesn't provide hashes
            )

        except Exception as e:
            print(f"Warning: Failed to process server item {item.get('Name', 'Unknown')}: {e}")
            return None
```

### 3. Registering Custom Importers

```python
# In your module or __init__.py
from retrovue.adapters.registry import SOURCES
from .jellyfin_importer import JellyfinImporter

# Register the importer
SOURCES["jellyfin"] = JellyfinImporter
```

## Creating Custom Enrichers

### 1. Basic Enricher Structure

```python
from typing import Any
from ..importers.base import DiscoveredItem
from .base import Enricher, EnricherError

class CustomEnricher:
    """Custom enricher for your specific metadata source."""

    name = "custom"

    def __init__(self, **kwargs):
        """Initialize with configuration."""
        # Store configuration parameters
        pass

    def enrich(self, discovered_item: DiscoveredItem) -> DiscoveredItem:
        """Enrich a discovered item with custom metadata."""
        try:
            # Skip if not applicable
            if not self._should_enrich(discovered_item):
                return discovered_item

            # Extract metadata
            metadata = self._extract_metadata(discovered_item)

            # Create enriched labels
            enriched_labels = discovered_item.raw_labels or []
            enriched_labels.extend(self._format_metadata(metadata))

            # Return enriched item
            return DiscoveredItem(
                path_uri=discovered_item.path_uri,
                provider_key=discovered_item.provider_key,
                raw_labels=enriched_labels,
                last_modified=discovered_item.last_modified,
                size=discovered_item.size,
                hash_sha256=discovered_item.hash_sha256
            )

        except Exception as e:
            raise EnricherError(f"Enrichment failed: {str(e)}") from e

    def _should_enrich(self, item: DiscoveredItem) -> bool:
        """Determine if item should be enriched."""
        # Implementation specific to your enricher
        return True

    def _extract_metadata(self, item: DiscoveredItem) -> dict[str, Any]:
        """Extract metadata from the item."""
        # Implementation specific to your enricher
        return {}

    def _format_metadata(self, metadata: dict[str, Any]) -> list[str]:
        """Format metadata as labels."""
        labels = []
        for key, value in metadata.items():
            labels.append(f"{key}:{value}")
        return labels
```

### 2. Metadata API Enricher Example

```python
import requests
from typing import Any
from ..importers.base import DiscoveredItem
from .base import Enricher, EnricherError

class MetadataAPIEnricher:
    """Example enricher using a metadata API (TheTVDB, TMDB, etc.)."""

    name = "metadata_api"

    def __init__(self, api_key: str, base_url: str = "https://api.example.com"):
        self.api_key = api_key
        self.base_url = base_url.rstrip('/')
        self.session = requests.Session()
        self._authenticate()

    def _authenticate(self):
        """Authenticate with metadata API."""
        auth_url = f"{self.base_url}/v4/login"
        auth_data = {"apikey": self.api_key}

        response = self.session.post(auth_url, json=auth_data)
        response.raise_for_status()

        token = response.json()["data"]["token"]
        self.session.headers.update({"Authorization": f"Bearer {token}"})

    def enrich(self, discovered_item: DiscoveredItem) -> DiscoveredItem:
        """Enrich with metadata API data."""
        try:
            if not self._should_enrich(discovered_item):
                return discovered_item

            # Extract title from path or labels
            title = self._extract_title(discovered_item)
            if not title:
                return discovered_item

            # Search metadata API for the title
            metadata = self._search_api(title)
            if not metadata:
                return discovered_item

            # Add metadata as labels
            enriched_labels = discovered_item.raw_labels or []
            enriched_labels.extend(self._format_metadata(metadata))

            return DiscoveredItem(
                path_uri=discovered_item.path_uri,
                provider_key=discovered_item.provider_key,
                raw_labels=enriched_labels,
                last_modified=discovered_item.last_modified,
                size=discovered_item.size,
                hash_sha256=discovered_item.hash_sha256
            )

        except Exception as e:
            raise EnricherError(f"Metadata API enrichment failed: {str(e)}") from e

    def _should_enrich(self, item: DiscoveredItem) -> bool:
        """Only enrich if it looks like a TV show."""
        # Check if path contains common TV show indicators
        tv_indicators = ['season', 'episode', 's0', 'e0', 'tv', 'series']
        path_lower = item.path_uri.lower()
        return any(indicator in path_lower for indicator in tv_indicators)

    def _extract_title(self, item: DiscoveredItem) -> str | None:
        """Extract title from path or labels."""
        # Try to extract from path
        # Implementation would parse the path to extract show name
        # This is a simplified example
        return "Example Show"

    def _search_api(self, title: str) -> dict[str, Any] | None:
        """Search metadata API for the title."""
        search_url = f"{self.base_url}/v4/search"
        params = {"query": title}

        response = self.session.get(search_url, params=params)
        response.raise_for_status()

        results = response.json().get("data", [])
        if results:
            return results[0]  # Return first match
        return None

    def _format_metadata(self, metadata: dict[str, Any]) -> list[str]:
        """Format metadata as labels."""
        labels = []

        if "name" in metadata:
            labels.append(f"api_title:{metadata['name']}")

        if "year" in metadata:
            labels.append(f"api_year:{metadata['year']}")

        if "genres" in metadata:
            for genre in metadata["genres"]:
                labels.append(f"api_genre:{genre}")

        if "status" in metadata:
            labels.append(f"api_status:{metadata['status']}")

        return labels
```

### 3. Registering Custom Enrichers

```python
# In your module or __init__.py
from retrovue.adapters.registry import register_enricher
from .tvdb_enricher import TVDBEnricher

# Register the enricher
register_enricher(TVDBEnricher())
```

## Integration with CLI

Once you've created and registered your custom importers and enrichers, they automatically become available in the CLI:

```bash
# List available types (includes your custom ones)
retrovue source list-types

# Use your custom importer
retrovue source add --type jellyfin --name "My Jellyfin Server" --server-url "http://jellyfin:8096" --api-key "your-key" --user-id "user123"

# Use your custom enricher
retrovue source add --type plex --name "Plex Server" --base-url "http://plex:32400" --token "token" --enrichers "tvdb"
```

## Best Practices

### 1. Error Handling

- Always wrap external API calls in try-catch blocks
- Use specific exception types (`ImporterError`, `EnricherError`)
- Provide meaningful error messages
- Log warnings for non-fatal issues

### 2. Configuration Validation

```python
def validate_config(config: dict) -> None:
    """Validate importer/enricher configuration."""
    required_fields = ['api_key', 'base_url']

    for field in required_fields:
        if field not in config:
            raise ImporterConfigurationError(f"Missing required field: {field}")
```

### 3. Resource Management

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

### 4. Testing

```python
import pytest
from unittest.mock import Mock, patch
from .jellyfin_importer import JellyfinImporter

class TestJellyfinImporter:
    def test_discover_basic(self):
        """Test basic discovery functionality."""
        with patch('requests.Session.get') as mock_get:
            mock_response = Mock()
            mock_response.json.return_value = {
                'Items': [
                    {
                        'Id': '12345',
                        'Name': 'Test Movie',
                        'MediaSources': [{'Path': '/path/to/movie.mp4', 'Size': 1000000}]
                    }
                ]
            }
            mock_get.return_value = mock_response

            importer = JellyfinImporter("http://test", "key", "user")
            items = importer.discover()

            assert len(items) == 1
            assert items[0].provider_key == '12345'
```

## File Organization

Place your custom importers and enrichers in the appropriate directories:

```
src/retrovue/adapters/
├── importers/
│   ├── base.py
│   ├── filesystem_importer.py
│   ├── plex_importer.py
│   └── jellyfin_importer.py  # Your custom importer
├── enrichers/
│   ├── base.py
│   ├── ffprobe_enricher.py
│   └── tvdb_enricher.py      # Your custom enricher
└── registry.py
```

## Documentation

When creating custom importers and enrichers, document:

1. **Purpose**: What the importer/enricher does
2. **Configuration**: Required and optional parameters
3. **Examples**: Usage examples with sample configurations
4. **Dependencies**: External libraries or services required
5. **Limitations**: Known issues or restrictions

---

_This guide provides comprehensive information for extending RetroVue. For more examples, see the existing importers and enrichers in the source code._
