# CatalogReconciliationContract v0.1

## Purpose

This contract governs how RetroVue keeps the catalog synchronized with external media sources. Reconciliation runs when a container refresh occurs. Reconciliation is deterministic and idempotent.

---

## Definitions

**Source**  
An external system providing media.

Examples:
- Plex
- Jellyfin
- Filesystem

**Container**  
A subdivision within a Source used for discovery.

Examples:
- Plex library
- filesystem directory
- Jellyfin library

**Locator**  
A unique address identifying media within a container.

Examples:
- `filesystem://movies/movie.mp4`
- `plex://library/12345`

**Media**  
A playable file associated with an Asset.

**Asset**  
A logical program entity scheduled for playout. Assets may contain multiple Media variants.

---

## Reconciliation Trigger

Reconciliation runs when a container refresh occurs. Reconciliation MAY be triggered by:

- scheduler daemon before playout horizon expansion
- operator CLI commands

---

## Reconciliation Workflow

Reconciliation steps, in order:

1. Discover locators within the container.
2. Detect sidecar metadata additions or changes associated with discovered media.
3. Compare discovered locators with catalog media records.
4. Determine reconciliation outcome.
5. Apply catalog mutations.
6. Enqueue processor jobs when required.

---

## Locator Identity

Media identity is defined by the tuple:

```
(source_id, container_id, locator)
```

(source_id, container_id, locator) MUST be unique across all Media records. Duplicate locators within a container are not permitted.

---

## Media Fingerprint

A Media fingerprint represents the physical identity of a media file. Typical fingerprint components include:

- file hash
- file size
- file modification timestamp

If the fingerprint changes while the locator remains the same, the Media record MUST be updated and dependent processors MUST be re-enqueued.

---

## Reconciliation Outcomes

| Source  | Catalog           | Action                          |
|---------|-------------------|---------------------------------|
| present | absent            | create asset + media            |
| present | present           | update media if fingerprint differs |
| present | present unchanged | no action                       |
| absent  | present           | mark media unavailable           |

---

## Media Creation

When a new locator is discovered, the system MUST create a new Asset unless explicit asset matching rules or operator action associates the Media with an existing Asset.

- create Media record
- create Asset if none exists
- attach media to asset
- enqueue processor jobs

---

## Media Update

If a locator already exists but the fingerprint has changed:

- update media fingerprint
- update metadata derived from the source
- enqueue processors dependent on media fingerprint

The system MUST NOT create a new Media entry.

---

## Media Retirement

If a locator previously known to the catalog is no longer present in the container:

- mark media unavailable
- do not delete the media record

This prevents loss of schedule history.

---

## Processor Job Creation

Reconciliation MUST enqueue processor jobs when:

- new media is discovered
- media fingerprint changes
- relevant sidecar metadata appears

Processors run asynchronously via the processor job queue.

---

## Idempotency

Reconciliation MUST be idempotent. Running reconciliation multiple times without source changes MUST produce no catalog changes.

---

## Interaction With Scheduling

Reconciliation occurs before playout horizon expansion. This ensures newly discovered media can be scheduled immediately.

---

## Observability

Reconciliation activity MUST be observable through logs and catalog mutation records. Observable events include:

- asset created
- media created
- media updated
- media marked unavailable
- processor jobs enqueued
