# Configuration Resolution — Domain Contract

Status: Contract
Authority Level: Cross-layer
Derived From: `LAW-IMMUTABILITY`, `LAW-DERIVATION`

---

## Overview

Configuration resolution is the process that combines global defaults with per-channel overrides into a single, fully-resolved, immutable configuration object consumed by runtime components.

Every tunable value in the system has exactly one authoritative default defined in `config/defaults.yaml`. Channels may override a subset of those defaults via their channel YAML files. The resolution process merges these two layers into a complete configuration — no key is missing, no ambiguity remains.

This contract governs how that merge is performed, what inputs are accepted, what the output guarantees, and how errors are handled. It does not govern how the configuration is loaded from disk, parsed, or injected into components — those are implementation concerns.

### Authority Boundary

This contract owns:
- The merge semantics between global defaults and channel overrides
- The precedence rules for conflicting values
- The completeness guarantee (no missing keys after resolution)
- The immutability guarantee (no mutation after resolution)
- The validation rules for input structure and types
- The null-handling semantics
- The list-replacement semantics

This contract does NOT own:
- The schema or content of `config/defaults.yaml` (owned by the defaults audit)
- The schema or content of channel YAML files (owned by `channel_dsl.md`)
- File loading, parsing, or disk I/O
- Runtime component behavior when reading resolved values
- Environment variable overrides (those are pre-resolution input transforms)

---

## Terminology

### Global Defaults

The file `config/defaults.yaml`. A hierarchical YAML document containing every tunable value in the system, organized by domain. This file is the single authoritative source of default values. Every key that any runtime component may read MUST exist in this file.

### Channel Configuration

A per-channel YAML file (e.g., `config/channels/hbo.yaml`). Contains channel-specific overrides for a subset of the global defaults. A channel configuration is not required to be complete — it declares only the values that differ from defaults. Channel configuration files also contain channel-specific domain data (pools, programs, schedule, traffic) that has no corresponding default.

### Resolved Configuration

The output of the merge process. A complete, immutable configuration object containing every key from the global defaults, with channel-specific overrides applied. This is the sole configuration object consumed by runtime components for a given channel.

### Override Key

A key present in both the global defaults and a channel configuration. The channel value takes precedence.

### Pass-through Key

A key present only in the channel configuration with no corresponding default (e.g., `pools`, `programs`, `schedule`). These keys are channel-specific domain data and pass through to the resolved configuration unchanged.

---

## 1. Inputs

### 1.1 Global Defaults (`config/defaults.yaml`)

The global defaults file MUST be a valid YAML document. It MUST contain a hierarchical dictionary structure organized by system domain. Every tunable value in the system MUST appear in this file exactly once.

The top-level keys are fixed domains:

| Domain | Scope |
|--------|-------|
| `scheduling` | Compilation, grid geometry, episode progression, EPG |
| `playout` | Segment construction, transitions, ad breaks, pacing, gRPC timeouts |
| `channel` | Per-channel runtime behavior, recovery, encoding format |
| `hls` | Segmentation, segment ring, viewer sessions |
| `streaming` | HTTP transport, ring buffers, backpressure, UDS |
| `system` | Ports, paths, database, logging, enrichment, metrics |
| `integrations` | Plex/HDHomeRun emulation, IPTV/XMLTV |
| `air` | C++ playout engine tunables |

Values within the defaults file MUST be typed: integer, float, string, boolean, list, or nested dictionary. No value may be null — every default MUST be a concrete value.

### 1.2 Channel Configuration (channel YAML)

A channel YAML file MUST be a valid YAML document. It MUST contain the key `channel` (the channel identifier). It MAY contain any subset of the keys present in the global defaults, using the same hierarchical path structure. It MAY also contain channel-specific domain keys (`pools`, `programs`, `schedule`, `traffic`, `format`) that have no corresponding default.

A channel configuration is not required to be complete. Omitted keys inherit from global defaults. A channel configuration MUST NOT introduce keys that exist in neither the global defaults nor the recognized channel-specific domain keys.

---

## 2. Output

### 2.1 Resolved Configuration Object

The resolved configuration MUST be a single object containing:

1. Every key from `config/defaults.yaml`, with values either inherited or overridden.
2. Every pass-through key from the channel configuration (`channel`, `number`, `name`, `pools`, `programs`, `schedule`, `traffic`, `format`, and any other channel-specific domain keys).

No key present in the global defaults may be absent from the resolved configuration. The resolved configuration MUST be complete — any runtime component reading any defined key MUST receive a value.

### 2.2 Completeness Guarantee

After resolution, for every leaf key `K` defined in `config/defaults.yaml`:
- If the channel configuration provides a value at path `K`, the resolved value is the channel's value.
- If the channel configuration does not provide a value at path `K`, the resolved value is the default.

There is no third case. Every leaf key has a resolved value.

---

## 3. Merge Rules

### 3.1 Dictionary Merge (Recursive)

When both the defaults and the channel configuration contain a dictionary at the same path, the dictionaries are merged recursively. Channel keys are applied on top of default keys. Default keys not present in the channel dictionary are preserved. Channel keys not present in the defaults are preserved (pass-through).

Example: if defaults define `playout.grpc.readiness_timeout_seconds: 10.0` and `playout.grpc.feed_timeout_seconds: 5.0`, and the channel overrides only `playout.grpc.feed_timeout_seconds: 3.0`, the resolved `playout.grpc` contains both keys: `readiness_timeout_seconds: 10.0` (inherited) and `feed_timeout_seconds: 3.0` (overridden).

### 3.2 Scalar Override

When both layers define a scalar value (integer, float, string, boolean) at the same leaf path, the channel value replaces the default value entirely. There is no partial merge of scalars.

### 3.3 List Replacement

When both layers define a list at the same path, the channel list replaces the default list entirely. Lists are NOT merged, appended, or deduplicated. The rationale: list semantics are order-dependent and domain-specific. Merging lists would require knowledge of what the list contains, which violates the resolution layer's domain-agnostic role.

### 3.4 Null Handling

An explicit `null` value in the channel configuration at a key that has a non-null default MUST clear the default — the resolved value is `null`. This is the mechanism for a channel to explicitly opt out of a default value. The resolution layer MUST distinguish between "key absent" (inherit default) and "key present with null value" (override to null). A key that is absent from the channel configuration MUST NOT be treated as null.

### 3.5 Type Preservation

The resolved value at any path MUST preserve the type of the overriding value. If the default is an integer and the channel provides a float, the resolved value is a float. Type validation (rejecting mismatches) is governed by Section 6, not by the merge process itself.

---

## 4. Precedence

The precedence order is absolute and has exactly two layers:

```
channel.yaml  >  defaults.yaml
```

Channel values override defaults. Defaults fill gaps. There are no other layers, no environment-specific defaults, and no runtime overrides within this contract.

Environment variable overrides (e.g., `RETROVUE_MIN_PREFEED_LEAD_TIME_MS`) are input transforms that modify the defaults before the merge process begins. They are not a third precedence layer — they alter the defaults layer itself. This contract does not govern environment variable handling.

---

## 5. Immutability Requirement

### INV-CONFIG-IMMUTABLE-001 — Resolved config is frozen after creation

The resolved configuration object MUST be treated as read-only from the moment it is created. No runtime component, callback, event handler, or operator action may mutate the resolved configuration. Components MUST read from the resolved configuration; they MUST NOT write to it.

If a configuration change is required at runtime, the correct action is to create a new resolved configuration object and replace the reference. The prior object MUST remain valid and unchanged for any component still holding a reference to it.

### INV-CONFIG-IDENTITY-001 — Stable identity within a channel activation

Within a single channel activation (from first viewer to teardown), the resolved configuration MUST NOT change. A channel activation operates against exactly one resolved configuration. If the underlying channel YAML or defaults file changes on disk, those changes take effect only on the next channel activation, not mid-activation.

---

## 6. Error Handling

### 6.1 Unknown Keys in Channel YAML

A channel YAML file MUST NOT contain keys within default-governed domains (e.g., `scheduling.foo_bar`) that do not exist in `config/defaults.yaml`. Unknown keys within these domains MUST be rejected. The resolution process MUST fail and MUST report the unknown key path.

Keys within channel-specific domains (`pools`, `programs`, `schedule`, `traffic`, `format`) are not validated against defaults — they are pass-through data governed by their own contracts.

### 6.2 Type Mismatches

When a channel overrides a default key, the override value's type MUST be compatible with the default's type:

| Default type | Accepted override types |
|-------------|------------------------|
| `int` | `int` |
| `float` | `int`, `float` |
| `str` | `str` |
| `bool` | `bool` |
| `list` | `list` |
| `dict` | `dict` |

A type mismatch MUST cause the resolution process to fail. The error MUST identify the key path, the expected type, and the actual type.

`int` overriding `float` is accepted (widening). `float` overriding `int` is NOT accepted (the default author declared integer semantics). `str` overriding `int` (or any other cross-category mismatch) is always rejected.

### 6.3 Invalid Structure

If the channel configuration provides a scalar where the defaults define a dictionary (or vice versa), the resolution process MUST fail. A scalar cannot override a subtree, and a subtree cannot override a scalar. The error MUST identify the key path and the structural conflict.

### 6.4 Missing Global Defaults File

If `config/defaults.yaml` does not exist or cannot be parsed, the system MUST NOT start. There is no fallback. The defaults file is mandatory.

### 6.5 Missing Channel Configuration

If a channel configuration file does not exist, the system MUST use the global defaults alone (plus the channel identifier provided by the startup request). This is not an error — channels are not required to override any defaults.

---

## 7. Example

### Global Defaults (excerpt)

```yaml
# config/defaults.yaml (excerpt)
channel:
  linger_seconds: 20
  encoding:
    video_bitrate_bps: 8000000
    aspect_policy: "preserve"
  recovery:
    base_delay_seconds: 1.0
    max_attempts: 5

hls:
  segmenter:
    target_duration_ms: 6000
    max_gop_ms: 1000
  ring:
    capacity: 7
    manifest_window: 3
  session:
    timeout_ms: 30000

playout:
  transitions:
    default_fade_duration_ms: 500
    default_type: "TRANSITION_NONE"
```

### Channel Configuration (excerpt)

```yaml
# config/channels/hbo.yaml (excerpt)
channel: hbo
number: 201
name: "Home Box Office"
channel_type: premium
timezone: America/New_York

channel:
  linger_seconds: 60
  encoding:
    video_bitrate_bps: 12000000

hls:
  segmenter:
    target_duration_ms: 4000

pools:
  movies_r:
    match:
      type: movie
      rating: R
```

### Resolved Configuration (result)

```yaml
# Channel "hbo" — resolved
channel:
  linger_seconds: 60                     # overridden (was 20)
  encoding:
    video_bitrate_bps: 12000000          # overridden (was 8000000)
    aspect_policy: "preserve"            # inherited from defaults
  recovery:
    base_delay_seconds: 1.0              # inherited from defaults
    max_attempts: 5                      # inherited from defaults

hls:
  segmenter:
    target_duration_ms: 4000             # overridden (was 6000)
    max_gop_ms: 1000                     # inherited from defaults
  ring:
    capacity: 7                          # inherited from defaults
    manifest_window: 3                   # inherited from defaults
  session:
    timeout_ms: 30000                    # inherited from defaults

playout:
  transitions:
    default_fade_duration_ms: 500        # inherited from defaults
    default_type: "TRANSITION_NONE"      # inherited from defaults

# Pass-through (channel-specific domain data, no defaults)
pools:
  movies_r:
    match:
      type: movie
      rating: R

# (All other defaults.yaml sections inherited in full)
```

Key observations:
- `channel.linger_seconds`: overridden (20 → 60)
- `channel.encoding.video_bitrate_bps`: overridden (8M → 12M)
- `channel.encoding.aspect_policy`: inherited — HBO overrode a sibling key, not this one
- `channel.recovery`: entire subtree inherited — HBO did not touch it
- `hls.segmenter.target_duration_ms`: overridden (6000 → 4000)
- `hls.segmenter.max_gop_ms`: inherited — sibling key untouched
- `pools`: pass-through — no default exists, channel data used as-is

---

## Invariant Summary

| ID | Title |
|----|-------|
| INV-CONFIG-IMMUTABLE-001 | Resolved config is frozen after creation |
| INV-CONFIG-IDENTITY-001 | Stable identity within a channel activation |

---

## Required Tests

- `server/tests/contracts/test_inv_config_resolution.py`

## Enforcement Evidence
TODO
