# Program Template Assembly — v1.0

**Status:** Foundational Contract
**Version:** 1.0

**Classification:** Domain (Content Assembly)
**Authority Level:** Planning (Tier 2 Resolution)
**Governs:** Template definition, structural node composition, template resolution lifecycle, duration enforcement, conditional evaluation
**Out of Scope:** Schedule slot assignment, episode selection, frame timing, segment composition, ad decisioning, runtime execution

---

## Domain — Program Template Assembly

### Purpose

Program Template Assembly is a declarative content assembly model. It defines the structural composition system applied at Tier 2 (Playlog horizon) to construct ordered playout segments from structural definitions.

Templates are not a scheduling authority. They do not assign time windows, select episodes, or influence grid geometry. Schedule Manager owns slot boundaries and editorial assignment. Templates operate strictly within those boundaries.

Templates are not a traffic system. They do not select advertisements, fill break slots, or manage interstitial inventory. Break markers within a template declare positions where external ad/filler systems insert content. The template itself carries no traffic logic.

Program Template Assembly is responsible for:

- Declaring the internal structure of a program event as an ordered tree of nodes.
- Resolving that tree into concrete, ordered playout segments during Tier 2 materialization.
- Enforcing duration constraints against the schedule-assigned time window.
- Surfacing resolution failures explicitly to the operator.

---

### Tier model

Two tiers govern the lifecycle of a scheduled program event. Templates interact with both but are resolved only at Tier 2.

#### Tier 1 — Schedule horizon

- Commits time windows to the broadcast grid.
- Commits the EPG identity string for each scheduled event.
- Stores a template reference (template ID) for each event.
- Does not resolve template internals. Template nodes, conditional rules, and asset references are opaque at Tier 1.
- Immutable after build. Tier 1 commitments are not modified unless the operator explicitly triggers a rebuild of the affected schedule window.

#### Tier 2 — Playlog horizon

- Resolves the referenced template into concrete, ordered playout segments.
- Applies conditional rules within the template tree.
- Applies structural node evaluation to produce asset references, break positions, and inclusion expansions.
- May re-randomize content selections on each Tier 2 build until the playout window becomes active. Non-determinism is permitted only before activation.
- Becomes immutable once the playout window enters the active execution window. No further re-resolution occurs after activation.

The boundary between Tier 1 and Tier 2 is a resolution boundary. Tier 1 stores what will air and when. Tier 2 resolves how the airing is internally structured.

---

### Template definition model

Templates live in channel configuration. Each channel's configuration contains the set of templates available for scheduling on that channel.

Templates are structural definitions. A template describes the internal composition of a program event as a tree of ordered nodes. Templates do not contain asset bytes, playback instructions, or execution-level detail.

Each template defines an EPG identity string. This string is the viewer-facing title committed to the EPG at Tier 1. The EPG identity string is a first-class property of the template, not derived or inferred.

Templates consist of nested nodes arranged in a tree structure. The root node represents the complete program event. Child nodes represent structural subdivisions: content selections, static asset placements, break markers, and template inclusions.

Templates may include other templates. A template node of inclusion type references another template by ID. The referenced template is expanded in place during resolution, producing a subtree within the parent. Maximum recursion depth is enforced. Resolution MUST reject any template tree that exceeds the configured maximum inclusion depth. Circular references are a hard failure.

Templates are tree-based and declarative. They describe structure, not procedure. Resolution traverses the tree and produces a flat, ordered sequence of concrete segments. The tree is the definition; the flat sequence is the output.

---

### Structural node model

Templates consist of ordered nodes. Each node occupies a position within the template tree and carries a type that determines its resolution behavior.

Nodes may represent:

- **Content selection.** A node that resolves to a primary content asset. Content selection nodes reference a content source (program, collection, or explicit asset) and produce a concrete asset reference during Tier 2 resolution. When Tier 1 has already committed a concrete asset (e.g., a specific movie), the content selection node adopts the pre-committed reference rather than performing independent resolution. When Tier 1 commits only a rule-based source (e.g., a collection with a selector mode), the content selection node resolves against that source at Tier 2.
- **Static asset.** A node that references a fixed, pre-determined asset (bumper, slate, ident). Static asset nodes do not involve selection logic; the asset reference is defined in the template.
- **Break marker.** A node that declares a position where external ad/filler systems insert content. Break markers carry duration constraints but no asset references. The template does not fill breaks; it declares their position and permitted duration. Break markers do not guarantee ad inventory availability. The external ad/filler system may underfill declared break durations; underfill handling is owned by that system, not by the template.
- **Template inclusion.** A node that references another template by ID. The referenced template is expanded in place during resolution, subject to recursion depth limits.

Node types are fixed and controlled in v1. The set of permitted node types is a closed enumeration. No user-defined or plugin-provided node types are supported in this version.

The architecture MUST allow expansion of the node type set in future versions without requiring structural changes to existing templates. New node types are additive.

---

### Duration invariants

Template resolution MUST NOT produce a total segment duration that exceeds the scheduled time window assigned at Tier 1. Overrun is a hard failure condition. A resolved template whose total duration exceeds the slot boundary MUST be rejected. The failure is surfaced to the operator as a resolution error.

Underfill is permitted. A resolved template whose total duration is less than the scheduled time window is valid. The difference between resolved duration and slot duration is handled externally by ad/filler systems. The template does not pad, stretch, or otherwise compensate for underfill.

Break marker durations are included in the total duration calculation. A template with 20 minutes of content and 5 minutes of declared break markers within a 30-minute slot has a total declared duration of 25 minutes and an underfill of 5 minutes.

Duration validation occurs at resolution time (Tier 2). Tier 1 stores only the template reference and the slot duration; it does not validate internal template duration at build time.

---

### Conditional evaluation model

Nodes within a template may contain conditional rules. Conditional rules gate node inclusion: a node with a condition is included in the resolved output only if the condition evaluates to true.

Conditions may inspect:

- **Primary content metadata.** Properties of the content asset selected by a content selection node (duration, genre, era, rating, format).
- **Calendar context.** Day of week, date, broadcast day boundaries, holiday flags, season.
- **Channel context.** Channel identifier, channel type, channel-level configuration properties.

Initial implementation supports single-branch evaluation. Each conditional rule evaluates to include or exclude. There is no else branch, no multi-way dispatch, and no fallback node selection in v1.

The architecture MUST support future additive rule stacking. Multiple conditions on a single node, compound boolean evaluation, and priority-ordered rule sets are anticipated extensions. The v1 model does not implement these but MUST NOT preclude them.

---

### Resolution lifecycle

Resolution occurs during Tier 2 materialization. When the Playlog horizon extends and a new playout window is generated, each scheduled event's template reference is resolved into concrete, ordered segments.

Resolution MUST NOT mutate template definitions. Templates are read-only inputs to the resolution process. Any state produced during resolution (concrete asset references, conditional evaluation results, expanded inclusion subtrees) is output state, not modification of the source template.

Resolution expands the template tree by:

1. Traversing nodes in tree order (depth-first, ordered children).
2. Evaluating conditional rules at each node.
3. Expanding template inclusion nodes recursively, subject to depth limits.
4. Resolving content selection nodes to concrete asset references.
5. Preserving static asset references as declared.
6. Emitting break markers with declared durations.
7. Producing a flat, ordered sequence of resolved segments.

Resolution is deterministic within a single Tier 2 build session. Given identical inputs (template definition, available assets, calendar context, channel context), resolution produces identical output. Randomized content selection uses a session-scoped seed; re-resolution within the same build session yields the same result. The seed MUST be stable for a given scheduled event within a single Tier 2 horizon build. A horizon build is one invocation of the Playlog horizon extension for a specific channel and time window. Daemon restarts or system restarts that trigger a new horizon build produce a new session and a new seed.

Once the playout window becomes active (enters the locked execution window), the resolved output is frozen. No re-resolution, re-randomization, or conditional re-evaluation occurs after activation.

---

### Failure behavior

Templates may fail resolution. Failure conditions include:

- Content selection node cannot resolve to a valid asset (no eligible content, resolver miss, asset not approved).
- Template inclusion references a nonexistent template ID.
- Template inclusion exceeds maximum recursion depth.
- Circular template inclusion detected.
- Resolved total duration exceeds the scheduled time window.
- Conditional rule references an unavailable context property.

Failure is explicit. A template that fails resolution produces no output. There is no partial resolution, no silent substitution, and no fallback to a default template.

Failures are comparable to compile-time validation errors. The template definition is the source; resolution is compilation; a failure means the source is invalid for the given context. The system does not emit a best-effort result.

Failures MUST surface to the operator. The resolution failure, its cause, the affected template ID, the affected channel, and the affected time window are reported through operator-visible channels. Silent failure is prohibited.

---

### Interaction with scheduling

Templates are structural only. They define the internal composition of a program event. They do not influence, modify, or constrain the schedule layer.

Templates do not influence slot duration. The schedule layer assigns time windows. Templates operate within those windows. A template cannot request a longer or shorter slot.

Templates do not adjust schedule windows. If a template's resolved duration does not match the slot duration, the slot duration is authoritative. The template conforms; the schedule does not adjust.

The schedule layer owns time boundaries. Slot start time, slot end time, and slot duration are schedule-layer commitments made at Tier 1. Templates have read-only visibility into slot duration for the purpose of duration validation. They have no write access to schedule state.

Templates MUST conform to schedule constraints. A template that cannot produce valid output within the assigned slot duration is a resolution failure, not a schedule modification request.

---

### Operator workflows

Operators define templates in channel configuration. Templates are authored as part of the channel's programming definition and are available for scheduling once defined.

Schedule references templates by ID. When an operator assigns a program event to a schedule slot, the assignment includes a template ID. The template ID links the editorial commitment (Tier 1) to the structural definition that will be resolved at Tier 2.

Tier 1 builds the schedule horizon. The schedule compiler produces grid-aligned program blocks with EPG identity strings and template references. This is an editorial commitment.

Tier 2 resolves structure. When the Playlog horizon extends into a scheduled window, the referenced template is resolved into concrete segments. Resolution applies conditional rules, expands inclusions, and produces the ordered playout sequence.

Manual rebuild is required to change Tier 1 commitments. Once a schedule window is built at Tier 1, the template reference and EPG identity string are locked. Changing the template assignment for a locked window requires an explicit operator-initiated rebuild of the affected schedule window.

---

### Naming rules

Template IDs MUST be unique per channel. No two templates within a single channel's configuration may share the same identifier.

The EPG identity string is explicitly defined in the template. Each template carries its own EPG-facing title as a declared property. The identity string is not derived from the template ID, not generated from asset metadata, and not inferred from content selection results.

The EPG identity string MUST NOT be auto-generated. Operators define the identity string. The system does not synthesize, concatenate, or otherwise construct EPG-facing titles from internal template properties.

Templates should follow stable naming conventions. Template IDs are channel-scoped identifiers referenced by schedule assignments. Renaming a template ID invalidates all schedule references to that ID. Naming conventions are operator-managed; the system enforces uniqueness but does not enforce a naming scheme.

---

**Document version:** 1.0
**Related:** [Program Event Scheduling Model (v1.0)](ProgramEventSchedulingModel_v1.0.md) · [Schedule Manager Planning Authority (v1.0)](ScheduleManagerPlanningAuthority_v1.0.md) · [Two-Tier Horizon Architecture](../architecture/two-tier-horizon.md) · [Programming DSL & Schedule Compiler](../contracts/core/programming_dsl.md)
**Governs:** Template definition, structural node composition, template resolution lifecycle, duration enforcement, conditional evaluation
