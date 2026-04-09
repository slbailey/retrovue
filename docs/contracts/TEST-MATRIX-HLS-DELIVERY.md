# TEST-MATRIX — HLS Delivery

Maps HLS delivery invariants to concrete test scenarios.

---

## Segment Production — Contract Invariants

| Invariant | Scenario | Test |
|-----------|----------|------|
| INV-HLS-SEGMENT-IDENTITY-001 | Segment indices are monotonically increasing with no gaps | `test_inv_hls_segment_production.py::test_segment_indices_monotonic` |
| INV-HLS-SEGMENT-IDENTITY-001 | Two segments never share the same index | `test_inv_hls_segment_production.py::test_segment_indices_unique` |
| INV-HLS-SEGMENT-IDENTITY-001 | Index counter survives producer restart within ChannelManager lifetime | `test_inv_hls_segment_production.py::test_index_survives_producer_restart` |
| INV-HLS-SEGMENT-KEYFRAME-001 | Every segment begins with an IDR frame | `test_inv_hls_segment_production.py::test_segment_starts_with_keyframe` |
| INV-HLS-SEGMENT-KEYFRAME-001 | Segment duration varies by at most one GOP from target | `test_inv_hls_segment_production.py::test_segment_duration_within_gop_tolerance` |
| INV-HLS-SEGMENT-IMMUTABLE-001 | Segment bytes identical across multiple reads | `test_inv_hls_segment_production.py::test_segment_bytes_immutable` |
| INV-HLS-SEGMENT-IMMUTABLE-001 | Completed segment fields cannot be modified | `test_inv_hls_segment_production.py::test_segment_fields_frozen` |
| INV-HLS-SEGMENT-WALLCLOCK-001 | Segment timestamp derived from BlockPlan, not system clock | `test_inv_hls_segment_production.py::test_segment_wallclock_from_blockplan` |
| INV-HLS-SEGMENT-WALLCLOCK-001 | Segment timestamp falls within active block time range | `test_inv_hls_segment_production.py::test_segment_wallclock_within_block_range` |
| INV-HLS-SEGMENT-SELFCONTAINED-001 | Every segment contains PAT and PMT | `test_inv_hls_segment_production.py::test_segment_contains_pat_pmt` |
| INV-HLS-SEGMENT-SELFCONTAINED-001 | Every segment contains at least one video frame | `test_inv_hls_segment_production.py::test_segment_nonempty_video` |

## Segment Production — Enforcement Invariants

| Invariant | Scenario | Test |
|-----------|----------|------|
| INV-HLS-SEGMENT-PTS-CONTINUITY-001 | Consecutive segments have continuous PTS within frame tolerance | `test_inv_hls_segment_timeline.py::test_pts_continuity_within_session` |
| INV-HLS-SEGMENT-PTS-CONTINUITY-001 | PTS break detected and flagged as discontinuity | `test_inv_hls_segment_timeline.py::test_pts_break_flags_discontinuity` |
| INV-HLS-SEGMENT-PTS-CONTINUITY-001 | PTS tracker resets on producer restart | `test_inv_hls_segment_timeline.py::test_pts_tracker_resets_on_restart` |
| INV-HLS-SEGMENT-INDEX-GUARD-001 | Index increments by exactly 1 per segment | `test_inv_hls_segment_timeline.py::test_index_increments_by_one` |
| INV-HLS-SEGMENT-INDEX-GUARD-001 | Counter force-corrects on detected drift | `test_inv_hls_segment_timeline.py::test_index_force_correction` |
| INV-HLS-SEGMENT-INDEX-GUARD-001 | Counter never decrements | `test_inv_hls_segment_timeline.py::test_index_never_decrements` |
| INV-HLS-SEGMENT-WALLCLOCK-AUDIT-001 | Timestamp within active block range passes audit | `test_inv_hls_segment_timeline.py::test_wallclock_audit_pass` |
| INV-HLS-SEGMENT-WALLCLOCK-AUDIT-001 | Timestamp outside block range logs warning, segment still pushed | `test_inv_hls_segment_timeline.py::test_wallclock_audit_fail_warns_and_pushes` |
| INV-HLS-SEGMENT-DURATION-BOUNDS-001 | Duration within tolerance passes silently | `test_inv_hls_segment_timeline.py::test_duration_within_bounds` |
| INV-HLS-SEGMENT-DURATION-BOUNDS-001 | Duration outside tolerance logs warning | `test_inv_hls_segment_timeline.py::test_duration_outside_bounds_warns` |
| INV-HLS-SEGMENT-DURATION-BOUNDS-001 | Zero-duration segment rejected with error | `test_inv_hls_segment_timeline.py::test_zero_duration_rejected` |

---

## Segment Ring — Contract Invariants

| Invariant | Scenario | Test |
|-----------|----------|------|
| INV-HLS-RING-BOUNDED-001 | Ring never exceeds declared capacity | `test_inv_hls_segment_ring.py::test_ring_capacity_not_exceeded` |
| INV-HLS-RING-BOUNDED-001 | Oldest segment evicted on overflow | `test_inv_hls_segment_ring.py::test_fifo_eviction_order` |
| INV-HLS-RING-BOUNDED-001 | Segments form contiguous index range | `test_inv_hls_segment_ring.py::test_contiguous_indices` |
| INV-HLS-RING-BOUNDED-001 | Evicted segment returns absence | `test_inv_hls_segment_ring.py::test_evicted_segment_returns_none` |
| INV-HLS-RING-OBSERVATION-001 | Segment retrievable immediately after push | `test_inv_hls_segment_ring.py::test_immediate_availability_after_push` |
| INV-HLS-RING-OBSERVATION-001 | Empty ring returns absence for all lookups | `test_inv_hls_segment_ring.py::test_empty_ring_returns_absence` |
| INV-HLS-RING-OBSERVATION-001 | Ring mutates only via push | `test_inv_hls_segment_ring.py::test_push_only_mutation` |
| INV-HLS-NO-DISK-IO-001 | No filesystem I/O on segment feed or serve path | `test_inv_hls_no_disk_io.py` |

## Segment Ring — Enforcement Invariants

| Invariant | Scenario | Test |
|-----------|----------|------|
| INV-HLS-RING-WINDOW-VALID-001 | Post-push consistency check: newest - oldest + 1 == len | `test_inv_hls_ring_integrity.py::test_window_consistency_after_push` |
| INV-HLS-RING-WINDOW-VALID-001 | Inconsistent state detected and self-repaired | `test_inv_hls_ring_integrity.py::test_window_self_repair_on_drift` |
| INV-HLS-RING-PUSH-ATOMIC-001 | Concurrent reader never observes len > capacity | `test_inv_hls_ring_integrity.py::test_concurrent_reader_capacity_bound` |
| INV-HLS-RING-PUSH-ATOMIC-001 | Concurrent reader never observes index gap | `test_inv_hls_ring_integrity.py::test_concurrent_reader_no_gap` |
| INV-HLS-RING-PUSH-ATOMIC-001 | window() and get() acquire same lock as push() | `test_inv_hls_ring_integrity.py::test_read_write_serialized` |
| INV-HLS-RING-EVICTION-GRACE-001 | Ring capacity > manifest window + 1 enforced at startup | `test_inv_hls_ring_integrity.py::test_capacity_exceeds_window_plus_grace` |
| INV-HLS-RING-EVICTION-GRACE-001 | Invalid capacity configuration rejected | `test_inv_hls_ring_integrity.py::test_invalid_capacity_rejected` |

---

## Manifest Publication — Contract Invariants

| Invariant | Scenario | Test |
|-----------|----------|------|
| INV-HLS-MANIFEST-LIVE-001 | Manifest does not contain EXT-X-ENDLIST while live | `test_inv_hls_manifest.py::test_no_endlist_while_live` |
| INV-HLS-MANIFEST-LIVE-001 | EXT-X-TARGETDURATION >= all EXTINF values | `test_inv_hls_manifest.py::test_targetduration_covers_all_segments` |
| INV-HLS-MANIFEST-SEQUENCE-001 | EXT-X-MEDIA-SEQUENCE equals oldest segment index | `test_inv_hls_manifest.py::test_media_sequence_equals_oldest_index` |
| INV-HLS-MANIFEST-SEQUENCE-001 | EXT-X-MEDIA-SEQUENCE never decreases | `test_inv_hls_manifest.py::test_media_sequence_monotonic` |
| INV-HLS-MANIFEST-SEQUENCE-001 | Segments listed in ascending index order | `test_inv_hls_manifest.py::test_segment_order_ascending` |
| INV-HLS-MANIFEST-SEQUENCE-001 | Segment URI stable across manifest versions | `test_inv_hls_manifest.py::test_segment_uri_stable` |
| INV-HLS-MANIFEST-PDT-001 | EXT-X-PROGRAM-DATE-TIME present before first segment | `test_inv_hls_manifest.py::test_program_date_time_present` |
| INV-HLS-MANIFEST-PDT-001 | PDT timestamp from MasterClock, not system clock | `test_inv_hls_manifest.py::test_pdt_from_masterclock` |
| INV-HLS-MANIFEST-PDT-001 | EXTINF matches segment stored duration | `test_inv_hls_manifest.py::test_extinf_matches_segment_duration` |
| INV-HLS-MANIFEST-CHANNEL-SCOPED-001 | Concurrent requests return identical manifest | `test_inv_hls_manifest.py::test_manifest_identical_for_concurrent_clients` |
| INV-HLS-MANIFEST-CHANNEL-SCOPED-001 | All listed segments present in ring | `test_inv_hls_manifest.py::test_manifest_segments_all_retrievable` |
| INV-HLS-DISCONTINUITY-MARKER-001 | EXT-X-DISCONTINUITY emitted for discontinuous segments | `test_inv_hls_discontinuity_marker.py` |

## Manifest Publication — Enforcement Invariants

| Invariant | Scenario | Test |
|-----------|----------|------|
| INV-HLS-MANIFEST-VALID-PLAYLIST-001 | Generated manifest contains EXTM3U, TARGETDURATION, MEDIA-SEQUENCE | `test_inv_hls_manifest_consistency.py::test_structural_validity` |
| INV-HLS-MANIFEST-VALID-PLAYLIST-001 | TARGETDURATION >= ceil of every EXTINF | `test_inv_hls_manifest_consistency.py::test_targetduration_ceiling` |
| INV-HLS-MANIFEST-VALID-PLAYLIST-001 | Malformed manifest returns 500 instead of being served | `test_inv_hls_manifest_consistency.py::test_malformed_manifest_returns_500` |
| INV-HLS-MANIFEST-SEQUENCE-MONOTONIC-001 | Sequence value never decreases across generations | `test_inv_hls_manifest_consistency.py::test_sequence_never_decreases` |
| INV-HLS-MANIFEST-SEQUENCE-MONOTONIC-001 | Sequence clamped to max on violation | `test_inv_hls_manifest_consistency.py::test_sequence_clamped_on_violation` |
| INV-HLS-MANIFEST-PDT-CLOCK-SOURCE-001 | PDT formatted from segment wall_clock_start_utc_ms only | `test_inv_hls_manifest_consistency.py::test_pdt_from_segment_field` |
| INV-HLS-MANIFEST-PDT-CLOCK-SOURCE-001 | Generator does not call system clock in PDT path | `test_inv_hls_manifest_consistency.py::test_no_system_clock_in_pdt` |
| INV-HLS-MANIFEST-PDT-CLOCK-SOURCE-001 | PDT in ISO 8601 UTC with millisecond precision | `test_inv_hls_manifest_consistency.py::test_pdt_format` |
| INV-HLS-MANIFEST-WINDOW-RING-ALIGNMENT-001 | Manifest built from single atomic ring snapshot | `test_inv_hls_manifest_consistency.py::test_atomic_snapshot` |
| INV-HLS-MANIFEST-WINDOW-RING-ALIGNMENT-001 | Empty ring returns 503 not empty playlist | `test_inv_hls_manifest_consistency.py::test_empty_ring_returns_503` |

---

## Viewer Presence — Contract Invariants

| Invariant | Scenario | Test |
|-----------|----------|------|
| INV-HLS-VIEWER-PRESENCE-001 | First request creates session and triggers first-viewer transition | `test_inv_hls_viewer_presence.py::test_first_request_creates_session` |
| INV-HLS-VIEWER-PRESENCE-001 | Subsequent requests refresh last-activity timestamp | `test_inv_hls_viewer_presence.py::test_request_refreshes_activity` |
| INV-HLS-VIEWER-PRESENCE-001 | Expired session reaped within timeout + reap_interval | `test_inv_hls_viewer_presence.py::test_expired_session_reaped` |
| INV-HLS-VIEWER-PRESENCE-001 | Simultaneous session creation triggers first-viewer once | `test_inv_hls_viewer_presence.py::test_concurrent_first_viewer_once` |
| INV-HLS-VIEWER-PRESENCE-001 | Session scoped to single channel | `test_inv_hls_viewer_presence.py::test_session_channel_scoped` |
| INV-HLS-PHANTOM-CLEANUP-001 | Failed startup cleans up phantom session | `test_inv_hls_phantom_cleanup.py` |

## Viewer Presence — Enforcement Invariants

| Invariant | Scenario | Test |
|-----------|----------|------|
| INV-HLS-VIEWER-COUNT-ACCURATE-001 | viewer_count == len(non_expired_sessions) after every mutation | `test_inv_hls_viewer_count.py::test_count_matches_sessions` |
| INV-HLS-VIEWER-COUNT-ACCURATE-001 | Count force-corrected on detected drift | `test_inv_hls_viewer_count.py::test_count_force_correction` |
| INV-HLS-VIEWER-COUNT-ACCURATE-001 | Create + increment atomic (no window of inconsistency) | `test_inv_hls_viewer_count.py::test_create_increment_atomic` |
| INV-HLS-SESSION-REAP-BOUNDED-001 | Reap interval <= timeout / 2 | `test_inv_hls_viewer_count.py::test_reap_interval_bound` |
| INV-HLS-SESSION-REAP-BOUNDED-001 | Expired session removed within timeout + reap_interval | `test_inv_hls_viewer_count.py::test_reap_timing_bound` |
| INV-HLS-SESSION-REAP-BOUNDED-001 | Reap timer cancelled on channel teardown | `test_inv_hls_viewer_count.py::test_reap_timer_cleanup` |
| INV-HLS-SESSION-FIRST-VIEWER-ONCE-001 | Concurrent session creation fires on_first_viewer exactly once | `test_inv_hls_viewer_count.py::test_first_viewer_exactly_once` |
| INV-HLS-SESSION-FIRST-VIEWER-ONCE-001 | on_first_viewer idempotent if called defensively | `test_inv_hls_viewer_count.py::test_first_viewer_idempotent` |
| INV-HLS-SESSION-FIRST-VIEWER-ONCE-001 | Last-viewer fires only when count reaches zero | `test_inv_hls_viewer_count.py::test_last_viewer_at_zero` |

---

## Channel Lifecycle — Contract Invariants

| Invariant | Scenario | Test |
|-----------|----------|------|
| INV-HLS-LIFECYCLE-SEGMENT-READY-001 | 503 with Retry-After during startup | `test_inv_hls_lifecycle.py::test_503_during_startup` |
| INV-HLS-LIFECYCLE-SEGMENT-READY-001 | No empty playlist served | `test_inv_hls_lifecycle.py::test_no_empty_manifest` |
| INV-HLS-LIFECYCLE-SEGMENT-READY-001 | Viewer joining active channel gets immediate manifest | `test_inv_hls_lifecycle.py::test_immediate_manifest_active_channel` |
| INV-HLS-LIFECYCLE-SEGMENT-READY-001 | Additional viewers do not affect production pipeline | `test_inv_hls_lifecycle.py::test_additional_viewers_no_pipeline_impact` |

## Channel Lifecycle — Enforcement Invariants

| Invariant | Scenario | Test |
|-----------|----------|------|
| INV-HLS-PRODUCER-SEGMENT-FLOW-001 | Warning at 2x target_duration stall while bytes flowing | `test_inv_hls_channel_runtime.py::test_stall_warning` |
| INV-HLS-PRODUCER-SEGMENT-FLOW-001 | Recovery triggered at 4x target_duration stall | `test_inv_hls_channel_runtime.py::test_stall_recovery` |
| INV-HLS-PRODUCER-SEGMENT-FLOW-001 | No stall warning when producer EOF (covered by liveness recovery) | `test_inv_hls_channel_runtime.py::test_no_stall_on_producer_eof` |
| INV-HLS-NO-ORPHAN-PRODUCER-001 | Producer stopped after linger expiry with zero viewers | `test_inv_hls_channel_runtime.py::test_producer_stopped_after_linger` |
| INV-HLS-NO-ORPHAN-PRODUCER-001 | Orphaned producer detected and torn down on health check | `test_inv_hls_channel_runtime.py::test_orphan_detected_on_health_check` |
| INV-HLS-NO-ORPHAN-PRODUCER-001 | Linger cancelled on viewer arrival | `test_inv_hls_channel_runtime.py::test_linger_cancelled_on_viewer` |
| INV-HLS-RESTART-DISCONTINUITY-001 | First segment after restart carries discontinuity flag | `test_inv_hls_channel_runtime.py::test_restart_discontinuity_flag` |
| INV-HLS-RESTART-DISCONTINUITY-001 | PTS tracker resets on restart | `test_inv_hls_channel_runtime.py::test_pts_tracker_reset_on_restart` |
| INV-HLS-RESTART-DISCONTINUITY-001 | Segment index continues from counter, not zero | `test_inv_hls_channel_runtime.py::test_index_continues_after_restart` |
| INV-HLS-RING-STALENESS-RECOVERY-001 | Stale ring returns 503, not 200 with old segments | `test_hls_stale_ring_recovery.py::test_stale_ring_returns_503` |
| INV-HLS-RING-STALENESS-RECOVERY-001 | Fresh ring within threshold returns normal 200 | `test_hls_stale_ring_recovery.py::test_fresh_ring_returns_200` |
| INV-HLS-RING-STALENESS-RECOVERY-001 | Stale ring triggers re-activation flag | `test_hls_stale_ring_recovery.py::test_stale_ring_triggers_reactivation` |
| INV-HLS-RING-STALENESS-RECOVERY-001 | Empty ring still returns 503 (no regression) | `test_hls_stale_ring_recovery.py::test_empty_ring_still_503` |
| INV-HLS-READINESS-001 | Ring below playable window → not ready | `test_hls_readiness.py::test_below_threshold_not_ready` |
| INV-HLS-READINESS-001 | Playable window reached → readiness signal set | `test_hls_readiness.py::test_threshold_reached_sets_signal` |
| INV-HLS-READINESS-001 | Readiness persists after threshold crossed | `test_hls_readiness.py::test_readiness_persists` |
| INV-HLS-READINESS-001 | Ring clear resets readiness | `test_hls_readiness.py::test_clear_resets_readiness` |
| INV-HLS-READINESS-001 | Warm channel serves immediately (no await) | `test_hls_readiness.py::test_warm_channel_no_await` |

---

## Endpoint Coexistence — Contract Invariants

| Invariant | Scenario | Test |
|-----------|----------|------|
| INV-HLS-ENDPOINT-COEXIST-001 | HLS and legacy TS viewers counted in same population | `test_inv_hls_endpoint_coexist.py::test_unified_viewer_count` |
| INV-HLS-ENDPOINT-COEXIST-001 | Single producer shared across both endpoints | `test_inv_hls_endpoint_coexist.py::test_single_producer_shared` |
| INV-HLS-ENDPOINT-COEXIST-001 | Correct Content-Type per endpoint | `test_inv_hls_endpoint_coexist.py::test_content_types` |
| INV-HLS-ENDPOINT-COEXIST-001 | Correct Cache-Control per endpoint | `test_inv_hls_endpoint_coexist.py::test_cache_control_headers` |
| INV-HLS-ENDPOINT-COEXIST-001 | Neither endpoint degraded by sibling activity | `test_inv_hls_endpoint_coexist.py::test_no_cross_endpoint_degradation` |

## Endpoint Coexistence — Enforcement Invariants

| Invariant | Scenario | Test |
|-----------|----------|------|
| INV-HLS-SERVE-BYTE-IDENTITY-001 | HTTP response body == ring segment data (no transformation) | `test_inv_hls_delivery_path.py::test_serve_byte_identity` |
| INV-HLS-SERVE-BYTE-IDENTITY-001 | Content-Length matches payload size | `test_inv_hls_delivery_path.py::test_content_length_accurate` |
| INV-HLS-SERVE-BYTE-IDENTITY-001 | Missing segment returns 404 not empty 200 | `test_inv_hls_delivery_path.py::test_missing_segment_404` |
| INV-HLS-MANIFEST-DETERMINISTIC-001 | Same ring snapshot produces byte-identical manifest | `test_inv_hls_delivery_path.py::test_manifest_deterministic` |
| INV-HLS-MANIFEST-DETERMINISTIC-001 | No system clock calls during manifest generation | `test_inv_hls_delivery_path.py::test_no_clock_in_manifest_gen` |
| INV-HLS-ENDPOINT-SESSION-TOUCH-001 | Successful 200 response refreshes session | `test_inv_hls_delivery_path.py::test_200_touches_session` |
| INV-HLS-ENDPOINT-SESSION-TOUCH-001 | 503 response does not refresh session | `test_inv_hls_delivery_path.py::test_503_no_touch` |
| INV-HLS-ENDPOINT-SESSION-TOUCH-001 | 404 response does not refresh session | `test_inv_hls_delivery_path.py::test_404_no_touch` |
| INV-HLS-ENDPOINT-SESSION-TOUCH-001 | Request with no session creates new session | `test_inv_hls_delivery_path.py::test_no_session_creates_new` |

---

## Slow Consumer Disconnect — Contract Invariants

| Invariant | Scenario | Test |
|-----------|----------|------|
| INV-SLOW-CONSUMER-DISCONNECT-001 | Overflow under disconnect policy sends EOF and removes subscriber | `test_slow_consumer_disconnect.py::TestDisconnectPolicyRemovesSlowClient::test_overflow_sends_eof_and_removes_subscriber` |
| INV-SLOW-CONSUMER-DISCONNECT-001 | Backpressure log contains structured client_id field | `test_slow_consumer_disconnect.py::TestDisconnectStructuredLogging::test_backpressure_log_contains_client_id` |
| INV-SLOW-CONSUMER-DISCONNECT-001 | drop_oldest policy keeps slow client connected (regression guard) | `test_slow_consumer_disconnect.py::TestDropOldestKeepsClientConnected::test_overflow_with_drop_oldest_keeps_subscriber` |
| INV-SLOW-CONSUMER-DISCONNECT-001 | Per-client state cleaned up after disconnect (no leaks) | `test_slow_consumer_disconnect.py::TestClientStateCleanupOnDisconnect::test_backpressure_log_state_cleaned_on_disconnect` |
| INV-SLOW-CONSUMER-DISCONNECT-001 | Disconnect log emitted with reason=backpressure_disconnect | `test_slow_consumer_disconnect.py::TestDisconnectReasonLog::test_disconnect_log_contains_reason_field` |
| INV-SLOW-CONSUMER-DISCONNECT-001 | Async generator breaks on write timeout (dead client) | `test_slow_consumer_disconnect.py::TestWriteTimeoutClosesConnection::test_yield_stall_exceeding_timeout_breaks_generator` |

## ChannelStream Fanout Metrics — Observability Invariants

| Invariant | Scenario | Test |
|-----------|----------|------|
| INV-LIFECYCLE-OBSERVABILITY-001 | Backpressure disconnect includes queue_bytes_at_detach | `test_channel_stream_metrics.py::TestBackpressureDisconnectQueueBytes::test_disconnect_log_includes_queue_bytes_at_detach` |
| INV-LIFECYCLE-OBSERVABILITY-001 | Write timeout includes client_id | `test_channel_stream_metrics.py::TestWriteTimeoutIncludesClientId::test_write_timeout_log_includes_client_id` |
| INV-LIFECYCLE-OBSERVABILITY-001 | First subscriber logs stream_state=fresh | `test_channel_stream_metrics.py::TestClientConnectedStreamState::test_first_subscriber_logs_stream_state_fresh` |
| INV-LIFECYCLE-OBSERVABILITY-001 | Subsequent subscriber logs stream_state=existing | `test_channel_stream_metrics.py::TestClientConnectedStreamState::test_second_subscriber_logs_stream_state_existing` |
| INV-LIFECYCLE-OBSERVABILITY-001 | Client disconnect includes queue_bytes_at_detach | `test_channel_stream_metrics.py::TestClientDisconnectedQueueBytes::test_unsubscribe_logs_queue_bytes_at_detach` |
