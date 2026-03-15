# Test Matrix — Plex Integration (HDHomeRun Virtual Tuner)

Covers: Plex adapter → ProgramDirector → ChannelManager → AIR lifecycle

---

## Discovery & Lineup

| Invariant | Test Scenario | Test File | Status |
|-----------|---------------|-----------|--------|
| INV-PLEX-DISCOVERY-001 | `/discover.json` returns all required HDHomeRun fields | `test_plex_discovery.py::TestPlexDiscovery::test_discover_contains_all_required_hdhomerun_fields` | TODO |
| INV-PLEX-DISCOVERY-001 | `TunerCount` equals registered channel count | `test_plex_discovery.py::TestPlexDiscovery::test_tuner_count_equals_channel_registry_size` | TODO |
| INV-PLEX-DISCOVERY-001 | `DeviceID` is stable across requests | `test_plex_discovery.py::TestPlexDiscovery::test_device_id_stable_across_calls` | TODO |
| INV-PLEX-DISCOVERY-001 | `LineupURL` resolves to adapter's own `/lineup.json` | `test_plex_discovery.py::TestPlexDiscovery::test_lineup_url_points_to_adapter_lineup` | TODO |
| INV-PLEX-DISCOVERY-001 | No hardware fiction fields in response | `test_plex_discovery.py::TestPlexDiscovery::test_discover_no_hardware_fiction_fields` | TODO |
| INV-PLEX-LINEUP-001 | One lineup entry per registered channel | `test_plex_lineup.py::TestPlexLineup::test_lineup_entry_count_matches_registry` | TODO |
| INV-PLEX-LINEUP-001 | `URL` points to valid `/channel/{id}.ts` endpoint | `test_plex_lineup.py::TestPlexLineup::test_url_points_to_channel_ts_endpoint` | TODO |
| INV-PLEX-LINEUP-001 | `GuideName` matches channel display name | `test_plex_lineup.py::TestPlexLineup::test_guide_name_matches_channel_display_name` | TODO |
| INV-PLEX-LINEUP-001 | No phantom channels in lineup | `test_plex_lineup.py::TestPlexLineup::test_no_phantom_channels` | TODO |
| INV-PLEX-TUNER-STATUS-001 | `ScanInProgress` is `0` | `test_plex_discovery.py::TestPlexDiscovery::test_tuner_status_scan_not_in_progress` | TODO |
| INV-PLEX-TUNER-STATUS-001 | `ScanPossible` is `1` | `test_plex_discovery.py::TestPlexDiscovery::test_tuner_status_scan_possible` | TODO |
| INV-PLEX-TUNER-STATUS-001 | Response invariant regardless of viewer count | `test_plex_discovery.py::TestPlexDiscovery::test_tuner_status_invariant_across_channel_counts` | TODO |

## Guide Data

| Invariant | Test Scenario | Test File | Status |
|-----------|---------------|-----------|--------|
| INV-PLEX-XMLTV-001 | Response is well-formed XMLTV XML | `test_plex_epg.py::TestPlexEPG::test_epg_xml_is_well_formed` | TODO |
| INV-PLEX-XMLTV-001 | Channel IDs match lineup `GuideNumber` | `test_plex_epg.py::TestPlexEPG::test_epg_xml_channel_ids_match_lineup_guide_numbers` | TODO |
| INV-PLEX-XMLTV-001 | Delegates to `generate_xmltv()` — no independent generation | `test_plex_epg.py::TestPlexEPG::test_epg_xml_delegates_to_generate_xmltv` | TODO |
| INV-PLEX-XMLTV-001 | Programme elements have required attributes | `test_plex_epg.py::TestPlexEPG::test_epg_xml_programme_has_start_stop_channel` | TODO |
| INV-PLEX-XMLTV-001 | Display name matches channel registry name | `test_plex_epg.py::TestPlexEPG::test_epg_xml_display_name_matches_channel_name` | TODO |

## Artwork

| Invariant | Test Scenario | Test File | Status |
|-----------|---------------|-----------|--------|
| INV-PLEX-ARTWORK-001 | Plex importer persists thumb_url in editorial payload | `test_plex_artwork.py::TestPlexArtworkIngest::test_thumb_url_persisted_in_editorial` | ✅ |
| INV-PLEX-ARTWORK-001 | Artwork resolver reads from editorial payload, no live API call | `test_plex_artwork.py::TestPlexArtworkResolve::test_resolve_from_editorial_no_api_call` | ✅ |
| INV-PLEX-ARTWORK-001 | Missing thumb_url returns placeholder, no fallback to live API | `test_plex_artwork.py::TestPlexArtworkResolve::test_missing_thumb_url_returns_none` | ✅ |
| INV-PLEX-ARTWORK-001 | XMLTV icon element uses persisted artwork URL | `test_plex_artwork.py::TestPlexArtworkXmltv::test_xmltv_icon_uses_persisted_thumb_url` | ✅ |

## Stream Lifecycle

| Invariant | Test Scenario | Test File | Status |
|-----------|---------------|-----------|--------|
| INV-PLEX-STREAM-START-001 | Stream request delegates to ProgramDirector | `test_plex_streaming.py::TestPlexStreaming::test_stream_start_delegates_to_program_director` | TODO |
| INV-PLEX-STREAM-START-001 | No independent AIR spawn or schedule compilation | `test_plex_streaming.py::TestPlexStreaming::test_stream_start_does_not_spawn_air_directly` | TODO |
| INV-PLEX-STREAM-START-001 | Correct channel_id passed through | `test_plex_streaming.py::TestPlexStreaming::test_stream_start_uses_channel_id_from_request` | TODO |
| INV-PLEX-STREAM-DISCONNECT-001 | Disconnect triggers `tune_out` | `test_plex_streaming.py::TestPlexStreaming::test_disconnect_triggers_tune_out` | TODO |
| INV-PLEX-STREAM-DISCONNECT-001 | `tune_out` called exactly once per `tune_in` | `test_plex_streaming.py::TestPlexStreaming::test_disconnect_tune_out_called_exactly_once` | TODO |
| INV-PLEX-STREAM-DISCONNECT-001 | Last Plex viewer out stops playout | `test_plex_streaming.py::TestPlexStreaming::test_last_viewer_disconnect_stops_producer` | TODO |
| INV-PLEX-STREAM-DISCONNECT-001 | No phantom viewer references after disconnect | `test_plex_streaming.py::TestPlexStreaming::test_disconnect_no_phantom_viewers` | TODO |

## Producer Fanout

| Invariant | Test Scenario | Test File | Status |
|-----------|---------------|-----------|--------|
| INV-PLEX-FANOUT-001 | Plex + direct viewers share same producer | `test_plex_streaming.py::TestPlexStreaming::test_plex_and_direct_viewers_share_producer` | TODO |
| INV-PLEX-FANOUT-001 | At most one AIR process per channel regardless of viewer origin | `test_plex_streaming.py::TestPlexStreaming::test_single_air_process_per_channel` | TODO |
| INV-PLEX-FANOUT-001 | No independent buffer or re-mux in adapter | `test_plex_streaming.py::TestPlexStreaming::test_adapter_has_no_independent_buffer` | TODO |
| INV-PLEX-FANOUT-001 | Mixed viewer disconnect order preserves counts | `test_plex_streaming.py::TestPlexStreaming::test_mixed_viewer_disconnect_order` | TODO |
