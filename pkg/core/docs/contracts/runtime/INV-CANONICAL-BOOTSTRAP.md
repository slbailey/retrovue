# INV-CANONICAL-BOOTSTRAP: Single Bootstrap Path Enforcement

**Component:** Core / ChannelManager
**Enforcement:** Runtime (`channel_manager.py`, `config.py`)
**Depends on:** INV-PLAYOUT-AUTHORITY, INV-JOIN-IN-PROGRESS-BLOCKPLAN
**Created:** 2026-02-07

---

## Purpose

When a channel is configured with `blockplan_only=True` in its
`ChannelConfig`, **only** the BlockPlanProducer + PlayoutSession
bootstrap path is permitted.  Any attempt to invoke the legacy
Phase8AirProducer / LoadPreview / SwitchToLive / playlist-tick path
MUST fail immediately with a `RuntimeError` containing the prefix
`INV-CANONICAL-BOOT`.

This guard ensures that the canonical entrypoints (`verify_first_on_air`,
`burn_in`) use exclusively the BlockPlan path, preventing accidental
regression to the deprecated producer when configuration or code changes.

---

## Scope

The guard is **opt-in per channel** via `ChannelConfig.blockplan_only`.
Channels that do not set this flag are unaffected — legacy code is
retained and callable for those channels.

---

## Configuration

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `blockplan_only` | `bool` | `False` | When `True`, ChannelManager rejects all legacy playout paths for this channel. |

Set in `ChannelConfig`:

```python
ChannelConfig(
    channel_id="retrovue-classic",
    ...,
    blockplan_only=True,
)
```

---

## Invariants

### INV-CANONICAL-BOOT-001: load_playlist Rejected

> Calling `load_playlist()` on a channel with `blockplan_only=True`
> raises `RuntimeError`.

**Rationale:** Loading a Playlist sets `_playlist`, which causes
`_build_producer_for_mode` to select Phase8AirProducer.  Blocking
the entry point prevents the entire legacy chain from activating.

---

### INV-CANONICAL-BOOT-002: Phase8AirProducer Selection Rejected

> `_build_producer_for_mode()` raises `RuntimeError` instead of
> returning `Phase8AirProducer` when `blockplan_only=True` and
> `_playlist is not None`.

**Rationale:** Defense-in-depth.  Even if `_playlist` is set by
means other than `load_playlist()`, the factory cannot produce a
legacy producer.

---

### INV-CANONICAL-BOOT-003: Playlist Bootstrap Rejected

> `_ensure_producer_running_playlist()` raises `RuntimeError` on a
> `blockplan_only=True` channel.

**Rationale:** This method is the legacy join-in-progress path
that resolves Playlist segments, builds a playout plan, and starts
Phase8AirProducer.  It must never execute for blockplan-only channels.

---

### INV-CANONICAL-BOOT-004: Playlist Tick Rejected

> `_tick_playlist()` raises `RuntimeError` on a `blockplan_only=True`
> channel.

**Rationale:** The playlist tick loop drives LoadPreview / SwitchToLive
segment transitions.  It must never execute for blockplan-only channels.

---

### INV-CANONICAL-BOOT-005: BlockPlanProducer Allowed

> The BlockPlanProducer path works normally for `blockplan_only=True`
> channels.  `_build_producer_for_mode()` returns `BlockPlanProducer`
> when `_blockplan_mode=True` and `_playlist is None`.

**Rationale:** The guard blocks legacy paths only; the canonical path
must remain functional.

---

## Constraints

### C1: No Legacy Code Deletion

The guard does NOT delete Phase8AirProducer, `_tick_playlist`,
`load_playlist`, or any other legacy code.  It only prevents
invocation on channels that opt in via `blockplan_only=True`.

### C2: Scope Limited to Configured Channels

Channels without `blockplan_only=True` are completely unaffected.
Existing tests that use Phase8AirProducer or Playlist-driven paths
continue to work.

---

## Required Tests

**File:** `pkg/core/tests/contracts/runtime/test_inv_canonical_bootstrap.py`

| Test Name | Invariant(s) | Description |
|-----------|-------------|-------------|
| `test_load_playlist_rejected` | 001 | `load_playlist()` raises on blockplan_only channel. |
| `test_phase8_producer_rejected` | 002 | `_build_producer_for_mode()` raises when _playlist is set on blockplan_only channel. |
| `test_playlist_bootstrap_rejected` | 003 | `_ensure_producer_running_playlist()` raises on blockplan_only channel. |
| `test_playlist_tick_rejected` | 004 | `_tick_playlist()` raises on blockplan_only channel. |
| `test_blockplan_producer_allowed` | 005 | `_build_producer_for_mode()` returns BlockPlanProducer on blockplan_only channel. |
| `test_non_blockplan_only_allows_legacy` | 001-004 | Without the flag, all legacy paths remain callable. |
| `test_error_message_contains_invariant_prefix` | 001-004 | Error messages contain "INV-CANONICAL-BOOT". |
