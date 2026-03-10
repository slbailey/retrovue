# INV-PLEX-XMLTV-001

## Behavioral Guarantee

The `/epg.xml` endpoint MUST return valid XMLTV guide data derived from the same source as the existing `/iptv/guide.xml` endpoint. The Plex adapter MUST NOT generate independent guide data.

## Authority Model

`generate_xmltv()` in `web/iptv.py` is the sole XMLTV generation authority. The Plex adapter MUST delegate to this function — it MUST NOT duplicate, filter, or transform the XMLTV output.

## Boundary / Constraint

- The response MUST be well-formed XMLTV XML.
- Channel IDs in the XMLTV output MUST match the `GuideNumber` values from `/lineup.json`.
- Programme entries MUST reflect the current EPG horizon — no stale or cached data independent of the EPG source.
- The adapter MUST NOT add, remove, or modify programme entries beyond what `generate_xmltv()` produces.

## Violation

XMLTV channel IDs do not match lineup `GuideNumber` values. Guide data diverges from EPG source. Adapter generates XMLTV independently of `generate_xmltv()`.

## Derives From

`LAW-CONTENT-AUTHORITY`, `LAW-DERIVATION`

## Required Tests

- `pkg/core/tests/contracts/plex/test_plex_epg.py`

## Enforcement Evidence

TODO
