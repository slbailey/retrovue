# INV-PLEX-ARTWORK-001

## Behavioral Guarantee

Every Plex-sourced asset MUST have its artwork URL persisted in `asset_editorial.payload` at ingest time. The XMLTV serving path MUST read artwork URLs from persisted editorial metadata — it MUST NOT make live upstream API calls to resolve artwork.

## Authority Model

The Plex importer (`plex_importer.py`) is the sole authority for artwork URL capture. The artwork resolver (`artwork.py`) reads from persisted state only.

## Boundary / Constraint

- The Plex importer MUST store `thumb_url` in `asset_editorial.payload` when `thumbUrl` is present in the Plex metadata response.
- The artwork resolver MUST resolve programme poster URLs from `asset_editorial.payload["thumb_url"]` without contacting the Plex server.
- The XMLTV `<icon>` element for each programme MUST contain a URL that resolves to artwork without live upstream API calls.
- If `thumb_url` is absent from editorial payload, the artwork endpoint MUST return a placeholder — it MUST NOT fall back to live Plex API resolution.

## Violation

Artwork URL is not persisted at ingest time. Serving path makes live API calls to Plex to resolve artwork. XMLTV `<icon>` elements are absent or unresolvable for Plex-sourced assets that have artwork in their source library.

## Derives From

`LAW-CONTENT-AUTHORITY`, `LAW-DERIVATION`

## Required Tests

- `pkg/core/tests/contracts/plex/test_plex_artwork.py`

## Enforcement Evidence

TODO
