// Repository: Retrovue-playout
// Component: MPEG-TS Playout Sink Configuration
// Purpose: Configuration structure for MpegTSPlayoutSink.
// Copyright (c) 2025 RetroVue

#ifndef RETROVUE_PLAYOUT_SINKS_MPEGTS_MPEGTS_PLAYOUT_SINK_CONFIG_HPP_
#define RETROVUE_PLAYOUT_SINKS_MPEGTS_MPEGTS_PLAYOUT_SINK_CONFIG_HPP_

#include <string>

namespace retrovue::playout_sinks::mpegts {

// Underflow policy when buffer is empty
enum class UnderflowPolicy {
  FRAME_FREEZE,  // Repeat last frame (default)
  BLACK_FRAME,   // Output black frame
  SKIP           // Skip output
};

// Configuration for MpegTSPlayoutSink
// POD struct - immutable after construction
struct MpegTSPlayoutSinkConfig {
  int port = 9000;                    // TCP server port (used if ts_socket_path is empty)
  std::string bind_host = "127.0.0.1"; // TCP bind address (default: localhost)
  std::string ts_socket_path;         // Unix domain socket path for TS output (if empty, use TCP)
  double target_fps = 30.0;           // Target frame rate
  int target_width = 640;             // Phase 8.6: per-channel fixed output width (all content scaled to this)
  int target_height = 480;            // Phase 8.6: per-channel fixed output height
  int bitrate = 5000000;              // Encoding bitrate (5 Mbps)
  int gop_size = 30;                  // GOP size (1 second at 30fps)
  bool stub_mode = false;             // Use stub mode (no real encoding)
  bool persistent_mux = false;        // Phase 8.4: if true, do not set resend_headers (no continuity reset)
  UnderflowPolicy underflow_policy = UnderflowPolicy::FRAME_FREEZE;
  bool enable_audio = false;          // Enable silent AAC audio
  size_t max_output_queue_packets = 100;  // Max packets in output queue before dropping
  size_t output_queue_high_water_mark = 80;  // High water mark: encode new frames only if queue below this

  // Prebuffer settings: buffer encoded data before sending to client.
  // This absorbs bitrate spikes during encoder warmup (fade-ins, etc.)
  double prebuffer_seconds = 2.0;  // Seconds of data to buffer before streaming starts
};

}  // namespace retrovue::playout_sinks::mpegts

#endif  // RETROVUE_PLAYOUT_SINKS_MPEGTS_MPEGTS_PLAYOUT_SINK_CONFIG_HPP_

