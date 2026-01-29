_Related: [Domain: Source](../domain/Source.md) • [Domain: Ingest pipeline](../domain/IngestPipeline.md) • [Operator CLI](../cli/README.md)_

# Source Management Features

## Overview

RetroVue's source management system provides a comprehensive solution for connecting to external media systems and managing content discovery workflows. The system supports multiple source types, automatic collection discovery, and flexible enricher management.

## Key Features

### 1. Automatic Collection Discovery

When adding a Plex source, collections (libraries) are automatically discovered and persisted to the database:

- **Automatic discovery**: No manual collection scanning required
- **Default state**: All collections start disabled (sync=false) and ingestible status depends on path mappings
- **Selective activation**: Enable only the collections you want for content discovery
- **Persistent storage**: Collection settings survive system restarts

### 2. Enricher Management

Update enrichers on existing sources without recreating them:

- **Runtime updates**: Add or remove enrichers without deleting sources
- **Multiple enrichers**: Support for comma-separated enricher lists
- **Validation**: Warnings for unknown enrichers while allowing them
- **Persistent storage**: Enricher settings stored in source configuration

### 3. Collection Management

Granular control over which content libraries participate in content discovery:

- **Enable/disable**: Toggle individual collections on/off
- **Bulk operations**: Manage multiple collections efficiently
- **Status tracking**: Clear visibility into which collections are active
- **Cascade deletion**: Deleting a source removes all related collections

## Supported Source Types

### Plex Media Server

- **Connection**: Base URL and authentication token
- **Automatic discovery**: Libraries automatically detected and persisted
- **Collection management**: Enable/disable individual libraries
- **Enricher support**: Add metadata enrichment to discovered content

### Filesystem

- **Path scanning**: Direct filesystem directory access
- **Pattern matching**: Configurable glob patterns for file discovery
- **Enricher support**: Add metadata enrichment to discovered content

## CLI Commands

### Source Management

```bash
# Add sources
retrovue source add --type plex --name "My Plex" --base-url "https://plex.example.com" --token "token"
retrovue source add --type filesystem --name "Media Library" --base-path "/media/movies"

# List and inspect sources
retrovue source list
retrovue source show "My Plex"

# Update sources
retrovue source update "My Plex" --name "Updated Plex"
retrovue source enrichers "My Plex" "ffprobe,metadata"

# Delete sources
retrovue source delete "My Plex" --force
```

### Collection Management

```bash
# View collections
retrovue source collections

# Enable/disable collections
retrovue source enable "Movies"
retrovue source enable "TV Shows"
retrovue source disable "Horror"

# Filter by source
retrovue source collections --source-id "My Plex"
```

## Workflow Examples

### Adding a Plex Source

1. **Add source**: `retrovue source add --type plex --name "My Plex Server" --base-url "https://plex.example.com" --token "your-token"`
2. **Automatic discovery**: Collections are discovered and persisted (all disabled by default)
3. **Enable collections**: `retrovue source enable "Movies"` to activate specific libraries
4. **Add enrichers**: `retrovue source enrichers "My Plex Server" "ffprobe"` for metadata enrichment

### Managing Collections

1. **View status**: `retrovue source collections` to see all collections and their enabled status
2. **Enable desired collections**: `retrovue source enable "Movies"` and `retrovue source enable "TV Shows"`
3. **Disable unwanted collections**: `retrovue source disable "Adult Content"`
4. **Update enrichers**: `retrovue source enrichers "My Plex Server" "ffprobe,metadata"`

## Database Schema

### Sources Table

- **id**: UUID primary key
- **external_id**: External system identifier (e.g., "plex-abc123")
- **name**: Human-readable source name
- **kind**: Source type ("plex", "filesystem")
- **config**: JSON configuration including enrichers
- **created_at/updated_at**: Timestamps

### Source Collections Table

- **id**: UUID primary key
- **source_id**: Foreign key to sources table
- **external_id**: External system identifier (e.g., Plex library key)
- **name**: Human-readable collection name
- **enabled**: Boolean flag for content discovery participation
- **config**: JSON configuration
- **created_at**: Timestamp

### Path Mappings Table

- **id**: UUID primary key
- **collection_id**: Foreign key to source_collections table
- **plex_path**: External system path
- **local_path**: Local filesystem path
- **created_at**: Timestamp

## Integration Points

### Content Discovery

- **IngestOrchestrator**: Consumes enabled collections for content discovery
- **SourceService**: Manages source lifecycle and collection discovery
- **ImporterRegistry**: Provides factory methods for creating importer instances

### Metadata Enrichment

- **EnricherRegistry**: Manages available enrichers
- **Source configuration**: Enrichers stored in source config JSON
- **Runtime application**: Enrichers applied during content discovery

## Best Practices

### Source Management

- Use descriptive names for sources
- Keep tokens and credentials secure
- Regularly review and clean up unused sources
- Use external IDs for programmatic access

### Collection Management

- Start with all collections disabled
- Enable only collections you need for content discovery
- Use descriptive collection names
- Monitor collection status regularly

### Enricher Management

- Start with basic enrichers (ffprobe)
- Add specialized enrichers as needed
- Test enricher combinations before production use
- Monitor enricher performance impact

## Troubleshooting

### Common Issues

1. **Collections not discovered**: Check Plex server connectivity and token validity
2. **Enrichers not applied**: Verify enricher names and source configuration
3. **Collections not enabled**: Use `retrovue source collections` to check status
4. **Source deletion fails**: Ensure no active content discovery is running

### Debug Commands

```bash
# Check source status
retrovue source show "Source Name"

# View all collections
retrovue source collections --json

# Test enricher availability
retrovue source list-types

# Verify source configuration
retrovue source show "Source Name" --json
```
