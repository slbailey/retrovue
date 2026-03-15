# ContainerDiscoveryContract v0.1

## Purpose

Defines how RetroVue discovers media from external systems.

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
A unique address identifying media within a container. Examples: filesystem path, Plex item ID.

---

## Rules

1. Media discovery MUST occur through Containers.

2. A Source MAY contain multiple Containers.

3. If a Source does not support subdivisions, a 1:1 Source → Container mapping MUST be created.

---

## Discovery Process

Container refresh performs:

1. discover locators
2. compare with catalog
3. apply reconciliation
4. enqueue processor jobs as required

---

## Reconciliation Outcomes

| Source  | Catalog | Action                          |
|---------|---------|---------------------------------|
| present | absent  | create asset + media           |
| present | present | update media if fingerprint changed |
| absent  | present | mark media unavailable         |

---

## Discovery Timing

Container refresh MUST run before playout horizon expansion.

This ensures new media is available for scheduling decisions.
