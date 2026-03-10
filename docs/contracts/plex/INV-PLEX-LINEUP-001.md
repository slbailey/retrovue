# INV-PLEX-LINEUP-001

## Behavioral Guarantee

The `/lineup.json` endpoint MUST return one entry per registered channel. Each entry MUST map to an existing RetroVue channel's MPEG-TS stream endpoint. The lineup MUST NOT invent channels, omit channels, or reference streams outside the RetroVue instance.

## Authority Model

`ProgramDirector`'s channel registry is the sole source of channel identity. The Plex adapter translates registry entries into HDHomeRun lineup format — it MUST NOT filter, reorder, or augment the channel list.

## Boundary / Constraint

- Each lineup entry MUST contain `GuideNumber`, `GuideName`, and `URL`.
- `GuideNumber` MUST be a unique, stable string per channel.
- `GuideName` MUST match the channel's display name from the channel registry.
- `URL` MUST resolve to the channel's MPEG-TS stream endpoint (`/channel/{id}.ts`).
- The lineup MUST contain exactly the channels present in the registry at the time of the request.

## Violation

Lineup entry references a channel not in the registry. Lineup omits a registered channel. `URL` resolves to a non-existent or incorrect stream endpoint.

## Derives From

`LAW-CONTENT-AUTHORITY`, `LAW-DERIVATION`

## Required Tests

- `pkg/core/tests/contracts/plex/test_plex_lineup.py`

## Enforcement Evidence

TODO
