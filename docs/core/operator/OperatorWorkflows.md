_Related: [Operator CLI](../cli/README.md) • [Content Library Workflow](ContentLibraryWorkflow.md) • [Domain: Enricher](../domain/Enricher.md) • [Runtime: Channel manager](../runtime/channel_manager.md)_

# Operator workflows

## Purpose

Give operators the typical flows they'll run using the CLI.

This document references the CLI contract. The CLI contract is the source of truth for syntax.

## Common workflows

### 1. Add a new Source and ingest it

1. List available Source types:
   - `retrovue source list-types`
2. Add a new Source instance:
   - `retrovue source add --type <type> --name <label> ...`
3. Discover collections from that Source:
   - `retrovue source discover <source_id>`
4. View collections and enable ingest on specific ones:
   - `retrovue collection list --source <source_id>`
   - `retrovue collection update <collection_id> --sync-enable --local-path /mnt/media/...`
5. Ingest:
   - `retrovue collection <collection_id> ingest`  
     or  
     `retrovue source <source_id> ingest`

### 2. Attach ingest enrichers

1. List available enricher types:
   - `retrovue enricher list-types`
2. Create an enricher instance:
   - `retrovue enricher add --type <type> --name <label> ...`
3. Attach it to the collection with a priority:
   - `retrovue collection attach-enricher <collection_id> <enricher_id> --priority <n>`

Lower priority number means it runs earlier.

### 3. Configure a Channel for playout

1. Create a Producer instance:
   - `retrovue producer add --type <type> --name <label> ...`
2. Confirm the Channel is associated with the correct Producer:
   - `retrovue channel list`
3. Configure playout enrichers and attach them with priorities:
   - `retrovue channel attach-enricher <channel_id> <enricher_id> --priority <n>`

### 4. Audit playout health

- `retrovue channel list` shows the active Producer and attached playout enrichers.
- As-run logs (internal) confirm what actually aired vs what was expected.

### 5. Complete Collection Reset (Nuclear Option)

When you need to completely start over with a collection:

1. **Preview what will be deleted** (always do this first):
   - `retrovue collection wipe "TV Shows" --dry-run`
2. **Actually wipe everything**:
   - `retrovue collection wipe "TV Shows"`
3. **Re-discover the collection** (if needed):
   - `retrovue source discover <source_id>`
4. **Re-ingest from scratch**:
   - `retrovue collection ingest "TV Shows"`

**⚠️ WARNING**: This deletes ALL data for the collection (assets, episodes, seasons, titles, review queue entries). The collection and path mappings are preserved for re-ingest.

**Use cases**:

- Collection has corrupted or inconsistent data
- Need to reset asset IDs back to 1
- Complete fresh start after schema changes
- Testing and development scenarios

See also:

- [CLI contract](../contracts/resources/README.md)
- [Enricher](../domain/Enricher.md)
- [Channel manager](../runtime/ChannelManager.md)
