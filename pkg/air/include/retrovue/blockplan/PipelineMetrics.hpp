// Repository: Retrovue-playout
// Component: Pipeline Metrics
// Purpose: Passive observability metrics for PipelineManager
// Contract Reference: PlayoutAuthorityContract.md
// Copyright (c) 2025 RetroVue
//
// Header-only.  All metric names use the "air_continuous_" prefix.
// These metrics are passive observations only — they do NOT affect
// execution, timing, or control flow.

#ifndef RETROVUE_BLOCKPLAN_PIPELINE_METRICS_HPP_
#define RETROVUE_BLOCKPLAN_PIPELINE_METRICS_HPP_

#include <cstdint>
#include <sstream>
#include <string>

namespace retrovue::blockplan {

struct PipelineMetrics {
  // ---- Session Lifetime ----
  int64_t session_start_epoch_ms = 0;
  int64_t session_duration_ms = 0;

  // ---- Frame Counters ----
  int64_t continuous_frames_emitted_total = 0;
  int64_t pad_frames_emitted_total = 0;

  // ---- Block Execution (P3.1a/P3.1b) ----
  int32_t source_swap_count = 0;
  int32_t total_blocks_executed = 0;

  // ---- Preload (P3.1b) ----
  int32_t next_preload_started_count = 0;
  int32_t next_preload_ready_count = 0;
  int32_t next_preload_failed_count = 0;
  int64_t fence_pad_frames_total = 0;

  // ---- Tick Deadline Discipline (INV-TICK-DEADLINE-DISCIPLINE-001) ----
  int64_t late_ticks_total = 0;

  // ---- Frame Cadence ----
  int64_t max_inter_frame_gap_us = 0;
  int64_t sum_inter_frame_gap_us = 0;
  int64_t frame_gap_count = 0;

  // ---- Audio Lookahead Buffer (INV-AUDIO-LOOKAHEAD-001) ----
  int32_t audio_buffer_depth_ms = 0;
  int64_t audio_buffer_underflows = 0;
  int64_t audio_buffer_samples_pushed = 0;
  int64_t audio_buffer_samples_popped = 0;

  // ---- Video Lookahead Buffer (INV-VIDEO-LOOKAHEAD-001) ----
  int32_t video_buffer_depth_frames = 0;
  int64_t video_buffer_underflows = 0;
  int64_t video_buffer_frames_pushed = 0;
  int64_t video_buffer_frames_popped = 0;

  // ---- Decode Latency ----
  int64_t decode_latency_p95_us = 0;
  int64_t decode_latency_mean_us = 0;

  // ---- Video Refill Rate ----
  double video_refill_rate_fps = 0.0;

  // ---- Buffer Low-Water Marks ----
  int32_t video_low_water_frames = 0;
  int32_t audio_low_water_ms = 0;
  int64_t video_low_water_events = 0;
  int64_t audio_low_water_events = 0;

  // ---- Session Detach (underflow-triggered stops) ----
  int32_t detach_count = 0;

  // ---- Encoder Lifetime ----
  int32_t encoder_open_count = 0;
  int32_t encoder_close_count = 0;
  int64_t encoder_open_ms = 0;

  // ---- Channel ----
  int32_t channel_id = 0;
  bool continuous_mode_active = false;

  // Generate Prometheus text exposition format
  std::string GeneratePrometheusText() const {
    std::ostringstream oss;
    const std::string ch = std::to_string(channel_id);

    // Session metrics
    oss << "# HELP air_continuous_session_duration_ms Duration of continuous output session\n";
    oss << "# TYPE air_continuous_session_duration_ms gauge\n";
    oss << "air_continuous_session_duration_ms{channel=\"" << ch << "\"} "
        << session_duration_ms << "\n";

    oss << "\n# HELP air_continuous_mode_active Whether a continuous output session is running\n";
    oss << "# TYPE air_continuous_mode_active gauge\n";
    oss << "air_continuous_mode_active{channel=\"" << ch << "\"} "
        << (continuous_mode_active ? 1 : 0) << "\n";

    // Frame counters
    oss << "\n# HELP air_continuous_frames_emitted_total Total frames emitted in session\n";
    oss << "# TYPE air_continuous_frames_emitted_total counter\n";
    oss << "air_continuous_frames_emitted_total{channel=\"" << ch << "\"} "
        << continuous_frames_emitted_total << "\n";

    oss << "\n# HELP air_continuous_pad_frames_emitted_total Total pad frames emitted in session\n";
    oss << "# TYPE air_continuous_pad_frames_emitted_total counter\n";
    oss << "air_continuous_pad_frames_emitted_total{channel=\"" << ch << "\"} "
        << pad_frames_emitted_total << "\n";

    // Block execution (P3.1)
    oss << "\n# HELP air_continuous_source_swap_count Source swap count (block transitions)\n";
    oss << "# TYPE air_continuous_source_swap_count counter\n";
    oss << "air_continuous_source_swap_count{channel=\"" << ch << "\"} "
        << source_swap_count << "\n";

    oss << "\n# HELP air_continuous_blocks_executed_total Total blocks executed\n";
    oss << "# TYPE air_continuous_blocks_executed_total counter\n";
    oss << "air_continuous_blocks_executed_total{channel=\"" << ch << "\"} "
        << total_blocks_executed << "\n";

    // Preload (P3.1b)
    oss << "\n# HELP air_continuous_next_preload_started_total Preloads started\n";
    oss << "# TYPE air_continuous_next_preload_started_total counter\n";
    oss << "air_continuous_next_preload_started_total{channel=\"" << ch << "\"} "
        << next_preload_started_count << "\n";

    oss << "\n# HELP air_continuous_next_preload_ready_total Preloads ready at fence\n";
    oss << "# TYPE air_continuous_next_preload_ready_total counter\n";
    oss << "air_continuous_next_preload_ready_total{channel=\"" << ch << "\"} "
        << next_preload_ready_count << "\n";

    oss << "\n# HELP air_continuous_next_preload_failed_total Preloads failed or not ready\n";
    oss << "# TYPE air_continuous_next_preload_failed_total counter\n";
    oss << "air_continuous_next_preload_failed_total{channel=\"" << ch << "\"} "
        << next_preload_failed_count << "\n";

    oss << "\n# HELP air_continuous_fence_pad_frames_total Pad frames at fence (next not ready)\n";
    oss << "# TYPE air_continuous_fence_pad_frames_total counter\n";
    oss << "air_continuous_fence_pad_frames_total{channel=\"" << ch << "\"} "
        << fence_pad_frames_total << "\n";

    // Tick deadline discipline
    oss << "\n# HELP air_continuous_late_ticks_total Ticks where monotonic now exceeded deadline\n";
    oss << "# TYPE air_continuous_late_ticks_total counter\n";
    oss << "air_continuous_late_ticks_total{channel=\"" << ch << "\"} "
        << late_ticks_total << "\n";

    // Frame cadence
    oss << "\n# HELP air_continuous_max_inter_frame_gap_us Maximum inter-frame gap (microseconds)\n";
    oss << "# TYPE air_continuous_max_inter_frame_gap_us gauge\n";
    oss << "air_continuous_max_inter_frame_gap_us{channel=\"" << ch << "\"} "
        << max_inter_frame_gap_us << "\n";

    double mean_gap = (frame_gap_count > 0)
        ? static_cast<double>(sum_inter_frame_gap_us) / frame_gap_count
        : 0.0;
    oss << "\n# HELP air_continuous_mean_inter_frame_gap_us Mean inter-frame gap (microseconds)\n";
    oss << "# TYPE air_continuous_mean_inter_frame_gap_us gauge\n";
    oss << "air_continuous_mean_inter_frame_gap_us{channel=\"" << ch << "\"} "
        << static_cast<int64_t>(mean_gap) << "\n";

    // Audio lookahead buffer
    oss << "\n# HELP air_continuous_audio_buffer_depth_ms Audio lookahead buffer depth (ms)\n";
    oss << "# TYPE air_continuous_audio_buffer_depth_ms gauge\n";
    oss << "air_continuous_audio_buffer_depth_ms{channel=\"" << ch << "\"} "
        << audio_buffer_depth_ms << "\n";

    oss << "\n# HELP air_continuous_audio_buffer_underflows Audio buffer underflow events\n";
    oss << "# TYPE air_continuous_audio_buffer_underflows counter\n";
    oss << "air_continuous_audio_buffer_underflows{channel=\"" << ch << "\"} "
        << audio_buffer_underflows << "\n";

    oss << "\n# HELP air_continuous_audio_buffer_samples_pushed Total samples pushed to audio buffer\n";
    oss << "# TYPE air_continuous_audio_buffer_samples_pushed counter\n";
    oss << "air_continuous_audio_buffer_samples_pushed{channel=\"" << ch << "\"} "
        << audio_buffer_samples_pushed << "\n";

    oss << "\n# HELP air_continuous_audio_buffer_samples_popped Total samples popped from audio buffer\n";
    oss << "# TYPE air_continuous_audio_buffer_samples_popped counter\n";
    oss << "air_continuous_audio_buffer_samples_popped{channel=\"" << ch << "\"} "
        << audio_buffer_samples_popped << "\n";

    // Video lookahead buffer
    oss << "\n# HELP air_continuous_video_buffer_depth_frames Video lookahead buffer depth (frames)\n";
    oss << "# TYPE air_continuous_video_buffer_depth_frames gauge\n";
    oss << "air_continuous_video_buffer_depth_frames{channel=\"" << ch << "\"} "
        << video_buffer_depth_frames << "\n";

    oss << "\n# HELP air_continuous_video_buffer_underflows Video buffer underflow events\n";
    oss << "# TYPE air_continuous_video_buffer_underflows counter\n";
    oss << "air_continuous_video_buffer_underflows{channel=\"" << ch << "\"} "
        << video_buffer_underflows << "\n";

    oss << "\n# HELP air_continuous_video_buffer_frames_pushed Total frames pushed to video buffer\n";
    oss << "# TYPE air_continuous_video_buffer_frames_pushed counter\n";
    oss << "air_continuous_video_buffer_frames_pushed{channel=\"" << ch << "\"} "
        << video_buffer_frames_pushed << "\n";

    oss << "\n# HELP air_continuous_video_buffer_frames_popped Total frames popped from video buffer\n";
    oss << "# TYPE air_continuous_video_buffer_frames_popped counter\n";
    oss << "air_continuous_video_buffer_frames_popped{channel=\"" << ch << "\"} "
        << video_buffer_frames_popped << "\n";

    // Decode latency
    oss << "\n# HELP air_continuous_decode_latency_p95_us P95 decode latency (microseconds)\n";
    oss << "# TYPE air_continuous_decode_latency_p95_us gauge\n";
    oss << "air_continuous_decode_latency_p95_us{channel=\"" << ch << "\"} "
        << decode_latency_p95_us << "\n";

    oss << "\n# HELP air_continuous_decode_latency_mean_us Mean decode latency (microseconds)\n";
    oss << "# TYPE air_continuous_decode_latency_mean_us gauge\n";
    oss << "air_continuous_decode_latency_mean_us{channel=\"" << ch << "\"} "
        << decode_latency_mean_us << "\n";

    // Video refill rate
    oss << "\n# HELP air_continuous_video_refill_rate_fps Video fill thread refill rate (fps)\n";
    oss << "# TYPE air_continuous_video_refill_rate_fps gauge\n";
    oss << "air_continuous_video_refill_rate_fps{channel=\"" << ch << "\"} "
        << video_refill_rate_fps << "\n";

    // Low-water events
    oss << "\n# HELP air_continuous_video_low_water_events Video buffer low-water events\n";
    oss << "# TYPE air_continuous_video_low_water_events counter\n";
    oss << "air_continuous_video_low_water_events{channel=\"" << ch << "\"} "
        << video_low_water_events << "\n";

    oss << "\n# HELP air_continuous_audio_low_water_events Audio buffer low-water events\n";
    oss << "# TYPE air_continuous_audio_low_water_events counter\n";
    oss << "air_continuous_audio_low_water_events{channel=\"" << ch << "\"} "
        << audio_low_water_events << "\n";

    // Session detach
    oss << "\n# HELP air_continuous_detach_count Underflow-triggered session stops\n";
    oss << "# TYPE air_continuous_detach_count counter\n";
    oss << "air_continuous_detach_count{channel=\"" << ch << "\"} "
        << detach_count << "\n";

    // Encoder lifetime
    oss << "\n# HELP air_continuous_encoder_open_count Encoder open count (must be 1)\n";
    oss << "# TYPE air_continuous_encoder_open_count counter\n";
    oss << "air_continuous_encoder_open_count{channel=\"" << ch << "\"} "
        << encoder_open_count << "\n";

    oss << "\n# HELP air_continuous_encoder_close_count Encoder close count (must be 1)\n";
    oss << "# TYPE air_continuous_encoder_close_count counter\n";
    oss << "air_continuous_encoder_close_count{channel=\"" << ch << "\"} "
        << encoder_close_count << "\n";

    oss << "\n# HELP air_continuous_encoder_open_ms Time to open encoder (ms)\n";
    oss << "# TYPE air_continuous_encoder_open_ms gauge\n";
    oss << "air_continuous_encoder_open_ms{channel=\"" << ch << "\"} "
        << encoder_open_ms << "\n";

    return oss.str();
  }
};

}  // namespace retrovue::blockplan

#endif  // RETROVUE_BLOCKPLAN_PIPELINE_METRICS_HPP_
