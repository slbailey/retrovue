### Content Library Workflow (Beginner’s Guide)

This guide walks operators end-to-end: add a source, discover containers, make a container ingestible, attach enrichers, ingest content, and review/approve assets for broadcast readiness.

Notes
- Replace example names/paths with your environment.
- All examples use bash syntax for Linux/Ubuntu/WSL.

### 1) Add a source

Add either a Plex source or a filesystem source. Start with a dry-run to validate parameters.

```bash
# List available source types
retrovue source list-types

# Filesystem example (recommended for first run)
retrovue source add --type filesystem --name "Local Media" --base-path "/media/movies" --dry-run

# Create the source (no dry-run)
retrovue source add --type filesystem --name "Local Media" --base-path "/media/movies"
```

Tip: For Plex, you’ll need a base URL and token.

### 2) Discover containers from the source

Discover “libraries” (containers) and persist them.

```bash
retrovue source discover "Local Media" --dry-run
retrovue source discover "Local Media"
```

Check the result:

```bash
retrovue container list --source "Local Media"
```

### 3) Make a container ingestible and enable sync

To ingest, a container must be ingestible (valid local path mapping) and typically sync-enabled. First set a local path mapping; then enable sync.

```bash
# Find your container's UUID or name
retrovue container list --source "Local Media"

# Provide a local path mapping (unlocks ingestible=true)
retrovue container update "Movies" --path-mapping "/media/movies"

# Enable sync (requires ingestible=true or --path-mapping in same command)
retrovue container update "Movies" --sync-enable
```

Verification: `retrovue container list --source "Local Media"` should show Sync=Enabled and Ingestable=Yes for the target container.

### 4) (Optional) Attach ingest enrichers to a container

Attach an enricher to run during ingest (e.g., ffprobe metadata). **For TV shows, attaching the ffprobe enricher is recommended** so that duration is probed from each media file and stored on the asset; episode id, title, and description are already captured from Plex into the asset’s editorial payload.

```bash
# Create an ffprobe enricher instance if you don't have one
retrovue enricher add --type ingest --name "FFprobe" --help   # then add with desired options

# List configured enricher instances (and/or add one via `retrovue enricher ...`)
retrovue enricher list

# Attach to a container with a priority (lower runs first)
retrovue container attach-enricher "Movies" enricher-ffprobe-1 --priority 1
retrovue container attach-enricher "TV Shows" enricher-ffprobe-1 --priority 1

# Detach when needed
retrovue container detach-enricher "Movies" enricher-ffprobe-1
```

Tip: If you haven’t created any enrichers yet, see `retrovue enricher add --help`.

### 5) Ingest content

Run a dry-run first to preview; then perform the ingest.

```bash
# Full container ingest (dry-run)
retrovue container ingest "Movies" --dry-run

# Full container ingest (executes writes)
retrovue container ingest "Movies"

# Targeted scopes
retrovue container ingest "TV Shows" --title "The Big Bang Theory"
retrovue container ingest "TV Shows" --title "The Big Bang Theory" --season 1
retrovue container ingest "TV Shows" --title "The Big Bang Theory" --season 1 --episode 1
```

Output includes counts for discovered/ingested/skipped/updated; use `--json` for machine-readable output and `--verbose-assets` to list created/updated asset IDs and URIs (source vs canonical) per the Container Ingest contract.

### 6) Review and approve assets (broadcast readiness)

Find assets that need attention, then approve and/or mark ready.

```bash
# List assets needing attention (downgraded or not yet approved)
retrovue asset attention --limit 100

# JSON variant
retrovue asset attention --json --limit 50

# Resolve a single asset (approve and mark ready)
retrovue asset resolve aaaaaaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa --approve --ready

# Read-only view for an asset
retrovue asset resolve aaaaaaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa
```

Guidance
- Approving sets `approved_for_broadcast=true`.
- Marking `--ready` advances state from enriching to ready where permitted.
- No commit occurs inside the usecase; the CLI handles the transaction boundary.

### 7) What’s next (toward broadcast)

- Keep containers synced and ingestible; schedule periodic ingests.
- Build out channel configuration and scheduling (see runtime docs) once a healthy set of assets is in `ready` with `approved_for_broadcast=true`.
- Use `retrovue container list-all` to survey ingestible/sync states across sources.

### Troubleshooting

- “Not ingestible” when enabling sync: add `--path-mapping` with a readable directory.
- “Source not found”: use the exact name, external ID, or UUID.
- Ingest dry-run shows actions but does not write; drop `--dry-run` to execute.
- Use `--json` everywhere for scripts/automation.


