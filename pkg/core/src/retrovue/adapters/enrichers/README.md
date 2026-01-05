# Enricher Development Guide

This guide explains how to create new enrichers for RetroVue using the provided skeleton template.

## Quick Start

1. **Copy the skeleton**: Use `src/retrovue/adapters/enrichers/base.py` as your starting point
2. **Create your enricher**: Follow the `ExampleEnricher` pattern in the skeleton
3. **Register your type**: Add your enricher to the registry system
4. **Test your implementation**: Ensure it passes contract tests

## Skeleton Components

### BaseEnricher Class

The `BaseEnricher` abstract class provides:

- **Configuration validation**: Automatic validation of required/optional parameters
- **Helper methods**: Utilities for creating enriched items and accessing config
- **Error handling**: Proper exception types for different failure modes
- **Contract compliance**: Ensures compatibility with RetroVue's domain model

### Required Implementation

Every enricher must implement:

```python
class MyEnricher(BaseEnricher):
    name = "my-enricher-type"  # Must be unique

    def enrich(self, discovered_item: DiscoveredItem) -> DiscoveredItem:
        # Your enrichment logic here
        pass

    @classmethod
    def get_config_schema(cls) -> EnricherConfig:
        # Define your parameters and scope
        pass
```

### Configuration Schema

Define your enricher's parameters using `EnricherConfig`:

```python
@classmethod
def get_config_schema(cls) -> EnricherConfig:
    return EnricherConfig(
        required_params=[
            {"name": "api_key", "description": "API key for external service"}
        ],
        optional_params=[
            {"name": "timeout", "description": "Request timeout in seconds", "default": "30"}
        ],
        scope="ingest",  # or "playout"
        description="Human-readable description of what this enricher does"
    )
```

## Implementation Patterns

### 1. File Processing Enrichers

For enrichers that process media files:

```python
def enrich(self, discovered_item: DiscoveredItem) -> DiscoveredItem:
    # Only process file:// URIs
    if not discovered_item.path_uri.startswith("file://"):
        return discovered_item

    # Extract file path
    file_path = Path(discovered_item.path_uri[7:])

    if not file_path.exists():
        raise EnricherError(f"File does not exist: {file_path}")

    # Process the file
    metadata = self._process_file(file_path)

    # Convert to labels
    labels = self._metadata_to_labels(metadata)

    return self._create_enriched_item(discovered_item, labels)
```

### 2. API-Based Enrichers

For enrichers that fetch data from external APIs:

```python
def enrich(self, discovered_item: DiscoveredItem) -> DiscoveredItem:
    try:
        # Extract identifier from item
        identifier = self._extract_identifier(discovered_item)

        # Fetch from API
        metadata = self._fetch_from_api(identifier)

        # Convert to labels
        labels = self._metadata_to_labels(metadata)

        return self._create_enriched_item(discovered_item, labels)

    except requests.RequestException as e:
        raise EnricherError(f"API request failed: {e}") from e
    except Exception as e:
        raise EnricherError(f"Enrichment failed: {e}") from e
```

### 3. Database Lookup Enrichers

For enrichers that query internal databases:

```python
def enrich(self, discovered_item: DiscoveredItem) -> DiscoveredItem:
    try:
        # Extract lookup key
        lookup_key = self._extract_lookup_key(discovered_item)

        # Query database
        metadata = self._query_database(lookup_key)

        if not metadata:
            return discovered_item  # No enrichment available

        # Convert to labels
        labels = self._metadata_to_labels(metadata)

        return self._create_enriched_item(discovered_item, labels)

    except Exception as e:
        raise EnricherError(f"Database lookup failed: {e}") from e
```

## Error Handling

### Exception Types

Use the appropriate exception type for different failure modes:

- `EnricherError`: General enrichment failures
- `EnricherConfigurationError`: Invalid configuration
- `EnricherTimeoutError`: Operation timeouts
- `EnricherNotFoundError`: Resource not found

### Graceful Degradation

Enrichers should never block ingestion or playout:

```python
def enrich(self, discovered_item: DiscoveredItem) -> DiscoveredItem:
    try:
        # Attempt enrichment
        return self._do_enrichment(discovered_item)
    except EnricherError:
        # Log the error but return original item
        logger.warning(f"Enrichment failed for {discovered_item.path_uri}")
        return discovered_item
```

## Testing

### Unit Tests

Test your enricher implementation:

```python
def test_enricher_enrichment():
    enricher = MyEnricher(api_key="test-key")
    item = DiscoveredItem(path_uri="file:///test.mp4", ...)

    enriched = enricher.enrich(item)

    assert enriched.raw_labels is not None
    assert "duration:120" in enriched.raw_labels
```

### Contract Compliance

Ensure your enricher works with the CLI contract:

```python
def test_enricher_cli_integration():
    # Test that your enricher can be created via CLI
    result = cli_runner.invoke(add_enricher, [
        "--type", "my-enricher",
        "--name", "Test Enricher",
        "--api-key", "test-key"
    ])

    assert result.exit_code == 0
```

## Registration

### Automatic Discovery

Place your enricher in `src/retrovue/adapters/enrichers/` with the naming pattern:

- `{enricher_type}_enricher.py`
- Example: `ffprobe_enricher.py`, `metadata_enricher.py`

### Manual Registration

If needed, register your enricher type:

```python
# In your enricher module
from ..base import register_enricher_type

class MyEnricher(BaseEnricher):
    # ... implementation ...

# Register the enricher type
register_enricher_type(MyEnricher)
```

## Best Practices

### 1. Stateless Design

Enrichers should be stateless and thread-safe:

```python
class MyEnricher(BaseEnricher):
    def __init__(self, **config):
        super().__init__(**config)
        # Store only configuration, no mutable state
        self.api_key = config["api_key"]
```

### 2. Efficient Processing

Only process items that need enrichment:

```python
def enrich(self, discovered_item: DiscoveredItem) -> DiscoveredItem:
    # Skip if already processed
    if self._is_already_enriched(discovered_item):
        return discovered_item

    # Skip unsupported file types
    if not self._supports_file_type(discovered_item):
        return discovered_item

    # Process the item
    return self._do_enrichment(discovered_item)
```

### 3. Label Format

Use consistent label formats:

```python
def _metadata_to_labels(self, metadata: Dict[str, Any]) -> List[str]:
    labels = []

    # Use consistent key:value format
    for key, value in metadata.items():
        # Normalize key names
        normalized_key = key.lower().replace(" ", "_")
        labels.append(f"{normalized_key}:{value}")

    return labels
```

### 4. Configuration Validation

Validate configuration parameters:

```python
def _validate_parameter_types(self) -> None:
    # Validate API key format
    api_key = self._safe_get_config("api_key")
    if not api_key or len(api_key) < 10:
        raise EnricherConfigurationError("API key must be at least 10 characters")

    # Validate timeout range
    timeout = self._safe_get_config("timeout", 30)
    if not isinstance(timeout, int) or timeout < 1 or timeout > 300:
        raise EnricherConfigurationError("Timeout must be between 1 and 300 seconds")
```

## Common Pitfalls

### 1. Modifying Original Items

❌ **Don't modify the original item:**

```python
def enrich(self, item: DiscoveredItem) -> DiscoveredItem:
    item.raw_labels.append("new:label")  # WRONG!
    return item
```

✅ **Create a new enriched item:**

```python
def enrich(self, item: DiscoveredItem) -> DiscoveredItem:
    new_labels = (item.raw_labels or []) + ["new:label"]
    return self._create_enriched_item(item, new_labels)
```

### 2. Blocking Operations

❌ **Don't block on external services:**

```python
def enrich(self, item: DiscoveredItem) -> DiscoveredItem:
    response = requests.get(url, timeout=None)  # WRONG!
```

✅ **Use timeouts and handle failures:**

```python
def enrich(self, item: DiscoveredItem) -> DiscoveredItem:
    try:
        response = requests.get(url, timeout=self.timeout)
    except requests.Timeout:
        raise EnricherTimeoutError("API request timed out")
    except requests.RequestException:
        return item  # Graceful degradation
```

### 3. Missing Configuration Validation

❌ **Don't assume configuration is valid:**

```python
def enrich(self, item: DiscoveredItem) -> DiscoveredItem:
    api_key = self.config["api_key"]  # May raise KeyError
```

✅ **Validate configuration:**

```python
def _validate_parameter_types(self) -> None:
    if "api_key" not in self.config:
        raise EnricherConfigurationError("API key is required")
```

## Examples

See the `ExampleEnricher` class in `base.py` for a complete working example that demonstrates all the patterns and best practices described in this guide.

## Support

For questions about enricher development:

1. Check the contract documentation in `docs/contracts/resources/EnricherAddContract.md`
2. Review the domain model in `docs/domain/Enricher.md`
3. Look at existing implementations like `ffprobe_enricher.py`
4. Run the contract tests to verify compliance
