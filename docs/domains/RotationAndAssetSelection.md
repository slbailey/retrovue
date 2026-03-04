# Rotation and Asset Selection — v1.0

**Status:** Foundational Contract
**Version:** 1.0

**Classification:** Domain (Selection Discipline)
**Authority Level:** Planning (Tier 2 Resolution + Playlog Materialization)
**Governs:** Asset warehouse usage, candidate querying, deterministic ordering, randomness policy, rotation memory, tentative/committed lifecycle, rebuild semantics, selection vs serialization boundary, lineage requirements
**Out of Scope:** Schedule slot assignment, template structure definition, ad decisioning logic, ffmpeg runtime execution, UI implementation

---

## Domain — Rotation and Asset Selection

### Purpose

Rotation and Asset Selection is the discipline that governs how assets and random content are chosen during broadcast assembly. It prevents repetition, enforces inventory diversity, and enables deterministic replay of selection decisions.

This domain operates at Tier 2 resolution time. It is invoked when template content selection nodes require concrete asset assignment from a candidate pool. It does not influence schedule structure, template composition, or runtime execution.

Rotation and Asset Selection is responsible for:

- Querying eligible candidates from the asset warehouse under tag and metadata constraints.
- Applying deterministic ordering and controlled randomness to candidate sets.
- Tracking per-channel rotation state to prevent excessive repetition.
- Managing the tentative/committed lifecycle of selection entries across horizon builds.
- Providing lineage data sufficient for auditability and debugging.

---

### Asset warehouse model

A single global asset warehouse holds all ingested assets. Assets are not duplicated across channels, categories, or schedule contexts. Each asset exists once; channels reference assets from the shared warehouse.

Assets carry metadata and tags. Tags are the primary mechanism for constraining candidate selection. Template content selection nodes declare tag-based criteria; the resolver queries the warehouse against those criteria.

There is no engine-level brand enforcement. The system does not validate brand consistency, thematic coherence, or editorial tone. Correctness of brand-aligned selections depends entirely on operator-maintained tag hygiene and the tag constraints declared in template selection criteria. If tags are incorrect or incomplete, selections will reflect that inaccuracy.

---

### Selection timing

Asset selection for template content nodes occurs during Tier 2 horizon expansion. Tier 1 commits structural and identity information (time windows, EPG identity strings, template references) but does not resolve content selection nodes.

When the Playlog horizon extends into a scheduled window, template resolution triggers content selection. The Rotation and Asset Selection discipline is active only during this Tier 2 resolution phase.

---

### Candidate querying and deterministic ordering

The resolver queries the asset warehouse for eligible candidates matching the tag and metadata constraints declared by a content selection node. The query produces a candidate set.

Candidate sets MUST be deterministically ordered before any randomness is applied. The ordering is a stable sort on defined, immutable properties of the candidates. The specific sort key is implementation-defined but MUST produce identical ordering given identical candidate sets across invocations.

Database natural order MUST NOT be relied upon. Query result ordering from the persistence layer is not guaranteed to be stable across restarts, schema migrations, or database engine updates. The resolver MUST apply its own deterministic sort after retrieval.

An empty candidate set after filtering is a selection failure. The resolver does not silently substitute from unrelated candidate pools.

---

### Randomness policy

Randomness in asset selection is controlled and reproducible. Uncontrolled randomness (system entropy, wall-clock-seeded PRNG) is prohibited during selection.

A horizon build has a persisted seed. The seed is generated once per build invocation, stored alongside the build record, and used as the root of all randomness for that build. A horizon build is one invocation of the Playlog horizon extension for a specific channel and time window. Daemon restarts or system restarts that trigger a new horizon build produce a new build record and a new seed.

Randomness is derived per node. Each content selection node derives its own PRNG state from the build seed and the node's identity within the template tree (node path). Nodes do not share a sequential PRNG stream. Inserting, removing, or reordering unrelated nodes in the template MUST NOT alter the random selection of other nodes.

Node-level derived randomness MUST be stable under refactoring. If a node's identity (template ID + node path) and the build seed are unchanged, the derived randomness produces the same selection regardless of changes to sibling or cousin nodes in the template tree.

The seed is stable for the lifetime of a horizon build. Re-resolution within the same build session yields identical selections. A new build session (triggered by operator rebuild or horizon re-extension) produces a new seed and may produce different selections.

The horizon build ID is a first-class identifier. It is persisted alongside playlog segment records and rotation entries. Any entity produced during a horizon build carries the build ID as part of its lineage.

---

### Rotation scope and ownership

Rotation state is scoped per channel, per asset. Each channel maintains independent rotation tracking. An asset's rotation history on one channel does not influence its eligibility on another channel.

When a content selection node selects from a pool of content items (episodes, shorts, movies), rotation applies per channel, per content item. The granularity is the selected entity, not the containing collection or series.

Rotation discipline is owned by a channel-level rotation service. Templates do not own, manage, or query rotation state directly. The resolver consults the rotation service during Tier 2 content selection. The rotation service is the single authority for rotation filtering on a given channel.

---

### Rotation policy

Rotation filtering applies to both committed and tentative entries. Within an active build context, tentative entries from the current build session are indistinguishable from committed entries for the purposes of rotation filtering. This prevents reuse within the same horizon build even when time-window constraints alone would permit it.

The primary rotation policy is time-window exclusion. An asset used on a channel within the configured time window is ineligible for reselection on that channel. The time window is configurable per channel.

If the time-window policy reduces the candidate set to empty, fallback to count-based exclusion applies. Count-based exclusion removes the last N uses from eligibility, where N is configurable per channel. This fallback permits reuse of assets outside the time window but still enforces minimum spacing in the selection sequence.

If count-based exclusion also reduces the candidate set to empty, degradation mode applies. In degradation mode, rotation constraints are relaxed and reuse is permitted. Degradation mode MUST be logged at warning level. The log entry includes the channel, time window, selector criteria, and the fact that rotation constraints were relaxed. Degradation is an inventory signal, not an operational error.

Rotation never causes a hard selection failure solely due to inventory scarcity. If eligible candidates exist (matching tag and metadata constraints), selection succeeds — with rotation constraints relaxed if necessary. Selection fails only when no candidates match the declared criteria at all, regardless of rotation state.

---

### Rotation persistence

Rotation state is persisted in the database. Rotation state is not held in memory only; process restarts do not lose rotation history.

Each rotation entry tracks at minimum the channel, the asset or content item identifier, and the timestamp of last use. Sufficient data is stored to support both time-window filtering and count-based filtering.

Rotation entries accumulate over time. Pruning of old rotation entries beyond the maximum configured time window is permitted but MUST NOT affect filtering accuracy for entries within the active window. Pruning must be safe to execute at any time without altering the behavior of active or pending rotation filtering.

---

### Tentative vs committed lifecycle

Tier 2 selection writes tentative rotation entries. When the resolver selects an asset during horizon expansion, the rotation entry is recorded as tentative. Tentative entries participate in rotation filtering for subsequent selections within the same build session, preventing duplicate selection within a single horizon build.

Tentative entries are committed upon actual segment emission. An entry transitions from tentative to committed when the playout producer starts and the corresponding segment begins airing. Commitment is an event driven by runtime activation, not by the passage of time.

If a Tier 2 window is rebuilt before activation, tentative entries from the prior build are removed. The new build starts with a clean tentative slate for the affected window. Previously committed entries from earlier windows are not affected.

If a window never airs (no viewers tune in, no producer starts), tentative entries for that window MUST NOT be committed. Unwatched windows do not pollute rotation history.

---

### Idempotency and rebuild semantics

Active windows are idempotent and frozen. Once a playout window enters the active execution window, its resolved selections are locked. Re-resolution does not occur. The selections are the selections.

Non-active windows may be rerolled. A non-active window's Tier 2 resolution may be discarded and rebuilt. Rerolling MUST rollback tentative rotation entries from the prior build before applying new selections.

Manual operator rebuild is the mechanism that triggers rerolling. The system does not automatically reroll non-active windows. An operator must explicitly initiate a rebuild of the affected schedule or playlog window.

The rebuild sequence is: rollback tentative entries for the affected window, generate a new build seed, resolve the template tree, write new tentative entries. The window returns to tentative state until activation.

---

### Selection vs serialization boundary

Rotation and selection semantics apply to randomly selected content. When a content selection node chooses from a pool based on tag criteria, rotation governs that choice.

Serialized progression is a distinct discipline. Serialized content (episode sequences, ordered playlists) advances according to schedule and playlist logic. Serialized progression tracks position in an ordered sequence and advances that position regardless of viewership. The next episode in a series is determined by sequence position, not by rotation filtering.

Serialized selection is not governed by rotation semantics. Rotation does not skip episodes, reorder series, or inject diversity into serialized progressions. If an operator schedules a series for sequential airing, rotation does not intervene.

The boundary is: rotation owns random selection from pools; serialization owns ordered advancement through sequences. These are separate authorities with no overlap.

---

### Playlog lineage requirements

When materializing playlog segments, the system MUST store lineage sufficient to explain each selection decision. Lineage is not optional metadata; it is a required output of the selection process.

Lineage includes at minimum:

- The template ID that defined the content selection node.
- The node path within the template tree.
- The horizon build ID that produced the selection.
- The channel ID on which the selection was made.
- The selected asset or content item identifier.

Lineage supports debugging and auditability. When an operator asks "why did this asset air at this time on this channel," the lineage chain provides a complete answer: which template, which node, which build, which channel, which asset.

Lineage is written alongside playlog segment records. It is not stored in a separate audit log that may diverge from the playlog.

---

### Failure behavior

Selection fails explicitly when no eligible candidates exist. If a content selection node's tag and metadata criteria match zero assets in the warehouse — before rotation filtering is even applied — selection fails. This is a hard failure.

No silent fallback to unrelated assets occurs. The system does not broaden criteria, relax tag constraints, or substitute from a different content pool. If the declared criteria produce no candidates, the resolution fails for that node.

Failures MUST surface to the operator at error level. The failure report includes the cause of failure, the affected channel, the affected time window, and the selector criteria that produced no candidates. Silent failure is prohibited.

Rotation-induced scarcity is not a failure condition. As defined in the rotation policy, rotation constraints degrade gracefully. Only the complete absence of matching candidates constitutes a selection failure.

---

**Document version:** 0.1
**Related:** [Program Template Assembly (v1.0)](ProgramTemplateAssembly.md) · [ScheduleItem](ScheduleItem.md) · [Horizon Manager (v0.1)](HorizonManager_v0.1.md) · [Schedule Manager Planning Authority (v0.1)](ScheduleManagerPlanningAuthority_v0.1.md)
**Governs:** Asset warehouse usage, candidate querying, deterministic ordering, randomness policy, rotation memory, tentative/committed lifecycle, rebuild semantics, selection vs serialization boundary, lineage requirements
