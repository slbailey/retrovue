// Repository: Retrovue-playout
// Component: Serial Block Baseline Metrics
// Purpose: Passive observability metrics for SerialBlockExecutionEngine
// Contract Reference: INV-SERIAL-BLOCK-EXECUTION, PlayoutAuthorityContract.md
// Copyright (c) 2025 RetroVue
//
// These metrics are passive observations only. They do NOT affect execution,
// timing, or control flow. They exist to lock in the baseline behavior of
// the SERIAL_BLOCK execution mode before any future modes are introduced.

#ifndef RETROVUE_BLOCKPLAN_SERIAL_BLOCK_METRICS_HPP_
#define RETROVUE_BLOCKPLAN_SERIAL_BLOCK_METRICS_HPP_

#include <cstdint>
#include <mutex>
#include <sstream>
#include <string>

namespace retrovue::blockplan {

// =============================================================================
// SerialBlockMetrics
// Accumulated per-session metrics for the serial block execution engine.
// Written by the engine thread, read by the metrics HTTP server thread.
// Thread-safety: all reads must go through Snapshot() or GeneratePrometheusText().
// =============================================================================

struct SerialBlockMetrics {
  // ---- Session Lifetime ----
  int64_t session_start_epoch_ms = 0;    // steady_clock epoch at session start
  int64_t session_end_epoch_ms = 0;      // steady_clock epoch at session end
  int64_t session_duration_ms = 0;       // end - start
  int32_t total_blocks_executed = 0;
  int64_t total_frames_emitted = 0;

  // ---- Frame Cadence (accumulated across all blocks) ----
  int64_t max_inter_frame_gap_us = 0;    // Worst-case gap between EmitFrame calls
  int64_t sum_inter_frame_gap_us = 0;    // Sum for computing mean
  int64_t frame_gap_count = 0;           // Number of inter-frame gaps measured
  int32_t frame_gaps_over_40ms = 0;      // Count of gaps exceeding 40ms

  // ---- Block Boundary ----
  int64_t max_boundary_gap_ms = 0;       // Worst block-to-block transition gap
  int64_t sum_boundary_gap_ms = 0;       // Sum for mean
  int32_t boundary_gaps_measured = 0;    // Number of transitions measured
  int64_t max_asset_probe_ms = 0;        // Worst per-block total probe time
  int64_t sum_asset_probe_ms = 0;        // Sum for mean
  int32_t assets_probed = 0;             // Total assets probed across all blocks

  // ---- Block Preloading (P2) ----
  int32_t preload_attempted_total = 0;       // Times preload was started
  int32_t preload_ready_at_boundary_total = 0; // Times preload was ready when needed
  int32_t preload_fallback_total = 0;        // Times fell back to sync probe
  int64_t max_preload_probe_us = 0;          // Worst preload probe time
  int64_t sum_preload_probe_us = 0;          // Sum for mean
  int64_t max_preload_decoder_open_us = 0;   // Worst preload decoder open
  int64_t sum_preload_decoder_open_us = 0;   // Sum for mean
  int64_t max_preload_seek_us = 0;           // Worst preload seek
  int64_t sum_preload_seek_us = 0;           // Sum for mean

  // ---- Encoder Lifetime ----
  int32_t encoder_open_count = 0;        // Must be exactly 1 per session
  int32_t encoder_close_count = 0;       // Must be exactly 1 per session
  int64_t encoder_open_ms = 0;           // Time to open encoder
  int64_t time_to_first_ts_packet_ms = 0; // Session start to first TS write

  // ---- Channel ----
  int32_t channel_id = 0;
  bool session_active = false;           // True while engine is running

  // Generate Prometheus text exposition format
  std::string GeneratePrometheusText() const {
    std::ostringstream oss;
    const std::string ch = std::to_string(channel_id);

    // Session metrics
    oss << "# HELP air_serial_block_session_duration_ms Duration of serial block session\n";
    oss << "# TYPE air_serial_block_session_duration_ms gauge\n";
    oss << "air_serial_block_session_duration_ms{channel=\"" << ch << "\"} "
        << session_duration_ms << "\n";

    oss << "\n# HELP air_serial_block_session_active Whether a serial block session is running\n";
    oss << "# TYPE air_serial_block_session_active gauge\n";
    oss << "air_serial_block_session_active{channel=\"" << ch << "\"} "
        << (session_active ? 1 : 0) << "\n";

    oss << "\n# HELP air_serial_block_blocks_executed_total Total blocks executed in session\n";
    oss << "# TYPE air_serial_block_blocks_executed_total counter\n";
    oss << "air_serial_block_blocks_executed_total{channel=\"" << ch << "\"} "
        << total_blocks_executed << "\n";

    oss << "\n# HELP air_serial_block_frames_emitted_total Total frames emitted in session\n";
    oss << "# TYPE air_serial_block_frames_emitted_total counter\n";
    oss << "air_serial_block_frames_emitted_total{channel=\"" << ch << "\"} "
        << total_frames_emitted << "\n";

    // Frame cadence
    oss << "\n# HELP air_serial_block_max_inter_frame_gap_us Maximum inter-frame gap (microseconds)\n";
    oss << "# TYPE air_serial_block_max_inter_frame_gap_us gauge\n";
    oss << "air_serial_block_max_inter_frame_gap_us{channel=\"" << ch << "\"} "
        << max_inter_frame_gap_us << "\n";

    double mean_gap = (frame_gap_count > 0)
        ? static_cast<double>(sum_inter_frame_gap_us) / frame_gap_count
        : 0.0;
    oss << "\n# HELP air_serial_block_mean_inter_frame_gap_us Mean inter-frame gap (microseconds)\n";
    oss << "# TYPE air_serial_block_mean_inter_frame_gap_us gauge\n";
    oss << "air_serial_block_mean_inter_frame_gap_us{channel=\"" << ch << "\"} "
        << static_cast<int64_t>(mean_gap) << "\n";

    oss << "\n# HELP air_serial_block_frame_gaps_over_40ms_total Count of inter-frame gaps exceeding 40ms\n";
    oss << "# TYPE air_serial_block_frame_gaps_over_40ms_total counter\n";
    oss << "air_serial_block_frame_gaps_over_40ms_total{channel=\"" << ch << "\"} "
        << frame_gaps_over_40ms << "\n";

    // Block boundary
    oss << "\n# HELP air_serial_block_max_boundary_gap_ms Maximum block-to-block transition gap (ms)\n";
    oss << "# TYPE air_serial_block_max_boundary_gap_ms gauge\n";
    oss << "air_serial_block_max_boundary_gap_ms{channel=\"" << ch << "\"} "
        << max_boundary_gap_ms << "\n";

    double mean_boundary = (boundary_gaps_measured > 0)
        ? static_cast<double>(sum_boundary_gap_ms) / boundary_gaps_measured
        : 0.0;
    oss << "\n# HELP air_serial_block_mean_boundary_gap_ms Mean block-to-block transition gap (ms)\n";
    oss << "# TYPE air_serial_block_mean_boundary_gap_ms gauge\n";
    oss << "air_serial_block_mean_boundary_gap_ms{channel=\"" << ch << "\"} "
        << static_cast<int64_t>(mean_boundary) << "\n";

    oss << "\n# HELP air_serial_block_max_asset_probe_ms Maximum per-block asset probe time (ms)\n";
    oss << "# TYPE air_serial_block_max_asset_probe_ms gauge\n";
    oss << "air_serial_block_max_asset_probe_ms{channel=\"" << ch << "\"} "
        << max_asset_probe_ms << "\n";

    oss << "\n# HELP air_serial_block_assets_probed_total Total assets probed across all blocks\n";
    oss << "# TYPE air_serial_block_assets_probed_total counter\n";
    oss << "air_serial_block_assets_probed_total{channel=\"" << ch << "\"} "
        << assets_probed << "\n";

    // Block preloading (P2)
    oss << "\n# HELP air_serial_block_preload_attempted_total Times preload was started\n";
    oss << "# TYPE air_serial_block_preload_attempted_total counter\n";
    oss << "air_serial_block_preload_attempted_total{channel=\"" << ch << "\"} "
        << preload_attempted_total << "\n";

    oss << "\n# HELP air_serial_block_preload_ready_total Times preload was ready at boundary\n";
    oss << "# TYPE air_serial_block_preload_ready_total counter\n";
    oss << "air_serial_block_preload_ready_total{channel=\"" << ch << "\"} "
        << preload_ready_at_boundary_total << "\n";

    oss << "\n# HELP air_serial_block_preload_fallback_total Times fell back to sync probe\n";
    oss << "# TYPE air_serial_block_preload_fallback_total counter\n";
    oss << "air_serial_block_preload_fallback_total{channel=\"" << ch << "\"} "
        << preload_fallback_total << "\n";

    if (preload_attempted_total > 0) {
      double mean_probe_us = static_cast<double>(sum_preload_probe_us) / preload_attempted_total;
      oss << "\n# HELP air_serial_block_preload_probe_us Preload asset probe time (microseconds)\n";
      oss << "# TYPE air_serial_block_preload_probe_us gauge\n";
      oss << "air_serial_block_preload_probe_max_us{channel=\"" << ch << "\"} "
          << max_preload_probe_us << "\n";
      oss << "air_serial_block_preload_probe_mean_us{channel=\"" << ch << "\"} "
          << static_cast<int64_t>(mean_probe_us) << "\n";
    }

    if (preload_ready_at_boundary_total > 0) {
      double mean_decoder_us = static_cast<double>(sum_preload_decoder_open_us) / preload_ready_at_boundary_total;
      double mean_seek_us = static_cast<double>(sum_preload_seek_us) / preload_ready_at_boundary_total;
      oss << "\n# HELP air_serial_block_preload_decoder_open_us Preload decoder open time (microseconds)\n";
      oss << "# TYPE air_serial_block_preload_decoder_open_us gauge\n";
      oss << "air_serial_block_preload_decoder_open_max_us{channel=\"" << ch << "\"} "
          << max_preload_decoder_open_us << "\n";
      oss << "air_serial_block_preload_decoder_open_mean_us{channel=\"" << ch << "\"} "
          << static_cast<int64_t>(mean_decoder_us) << "\n";

      oss << "\n# HELP air_serial_block_preload_seek_us Preload seek time (microseconds)\n";
      oss << "# TYPE air_serial_block_preload_seek_us gauge\n";
      oss << "air_serial_block_preload_seek_max_us{channel=\"" << ch << "\"} "
          << max_preload_seek_us << "\n";
      oss << "air_serial_block_preload_seek_mean_us{channel=\"" << ch << "\"} "
          << static_cast<int64_t>(mean_seek_us) << "\n";
    }

    // Encoder lifetime
    oss << "\n# HELP air_serial_block_encoder_open_count Encoder open count (must be 1)\n";
    oss << "# TYPE air_serial_block_encoder_open_count counter\n";
    oss << "air_serial_block_encoder_open_count{channel=\"" << ch << "\"} "
        << encoder_open_count << "\n";

    oss << "\n# HELP air_serial_block_encoder_close_count Encoder close count (must be 1)\n";
    oss << "# TYPE air_serial_block_encoder_close_count counter\n";
    oss << "air_serial_block_encoder_close_count{channel=\"" << ch << "\"} "
        << encoder_close_count << "\n";

    oss << "\n# HELP air_serial_block_encoder_open_ms Time to open encoder (ms)\n";
    oss << "# TYPE air_serial_block_encoder_open_ms gauge\n";
    oss << "air_serial_block_encoder_open_ms{channel=\"" << ch << "\"} "
        << encoder_open_ms << "\n";

    oss << "\n# HELP air_serial_block_time_to_first_ts_ms Time from session start to first TS packet (ms)\n";
    oss << "# TYPE air_serial_block_time_to_first_ts_ms gauge\n";
    oss << "air_serial_block_time_to_first_ts_ms{channel=\"" << ch << "\"} "
        << time_to_first_ts_packet_ms << "\n";

    return oss.str();
  }
};

}  // namespace retrovue::blockplan

#endif  // RETROVUE_BLOCKPLAN_SERIAL_BLOCK_METRICS_HPP_
