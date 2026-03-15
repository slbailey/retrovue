# AssetMediaIdentityContract v0.1

## Purpose

Defines the identity relationship between Assets and Media in the RetroVue catalog.

The catalog represents logical programs (Assets) and their playable file variants (Media).

---

## Definitions

**Asset**  
A logical program unit that may be scheduled for playout.

Examples:
- a movie
- an episode
- a commercial

**Media**  
A concrete playable file associated with an Asset.

Examples:
- movie.mp4
- movie_bluray.mkv
- movie_fullscreen.mkv

---

## Rules

1. Every discovered Media MUST belong to exactly one Asset.

2. An Asset MAY contain multiple Media variants.

3. The scheduler schedules Assets, not Media.

4. The playout system selects the Media variant at runtime.

---

## Media Identity

Media identity is defined by:

```
(source_id, container_id, locator)
```

The tuple (source_id, container_id, locator) MUST uniquely identify a Media record. Duplicate locators within a container are not permitted.

Examples:

- `filesystem://movies/movie.mp4`
- `plex://library/12345`

---

## Media Replacement

When a locator already exists but the media fingerprint changes, the system MUST update the Media record's fingerprint and metadata and enqueue processor jobs as required. A new Media entry MUST NOT be created.

---

## Media Variants

Multiple Media objects may exist under one Asset when locators differ.

Example:

- `ghostbusters_fullscreen.mkv`
- `ghostbusters_widescreen.mkv`

These are separate Media entries attached to the same Asset.

---

## Media Availability

If a locator disappears from the source during reconciliation, the Media record MUST NOT be deleted. Instead it MUST be marked unavailable.

---

## Duplicate Detection

If discovery detects Media likely belonging to an existing Asset, the system SHOULD flag it for operator review.

Operator may:

- attach media to existing asset
- create new asset
- ignore
