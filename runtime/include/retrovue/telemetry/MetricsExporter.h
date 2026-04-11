// Repository: Retrovue-playout
// Component: Metrics Exporter
// Purpose: Exposes Prometheus metrics at /metrics HTTP endpoint.
// Copyright (c) 2025 RetroVue

#ifndef RETROVUE_TELEMETRY_METRICS_EXPORTER_H_
#define RETROVUE_TELEMETRY_METRICS_EXPORTER_H_

#include <atomic>
#include <chrono>
#include <condition_variable>
#include <functional>
#include <map>
#include <memory>
#include <mutex>
#include <optional>
#include <string>
#include <thread>
#include <vector>

namespace retrovue::telemetry {

// Forward declaration
class MetricsHTTPServer;

// ChannelState represents the current state of a playout channel.
enum class ChannelState {
  STOPPED = 0,
  BUFFERING = 1,
  READY = 2,
  ERROR_STATE = 3
};

// Convert ChannelState to string for metrics output.
const char* ChannelStateToString(ChannelState state);

// ChannelMetrics holds per-channel telemetry data.
struct ChannelMetrics {
  ChannelState state;
  uint64_t buffer_depth_frames;
  double frame_gap_seconds;
  uint64_t decode_failure_count;
  uint64_t corrections_total;
  
  ChannelMetrics()
      : state(ChannelState::STOPPED),
        buffer_depth_frames(0),
        frame_gap_seconds(0.0),
        decode_failure_count(0),
        corrections_total(0) {}
};

// MetricsExporter serves Prometheus metrics at an HTTP endpoint.
//
// Phase 2 Implementation:
// - Simple HTTP server serving /metrics endpoint
// - Text-based Prometheus exposition format
// - Thread-safe metric updates
//
// Metrics Exported:
// - retrovue_playout_channel_state{channel="N"} - gauge
// - retrovue_playout_buffer_depth_frames{channel="N"} - gauge
// - retrovue_playout_frame_gap_seconds{channel="N"} - gauge
// - retrovue_playout_decode_failure_count{channel="N"} - counter
//
// Usage:
// 1. Construct with port number
// 2. Call Start() to begin serving metrics
// 3. Update metrics using SubmitChannelMetrics()
// 4. Call Stop() to shutdown server
class MetricsExporter {
 public:
  enum class Transport {
    kGrpcStream = 0,
    kScrape = 1,
    kFile = 2,
  };

  struct TransportSnapshot {
    uint64_t deliveries = 0;
    uint64_t failures = 0;
    double latency_p95_ms = 0.0;
  };

  struct Snapshot {
    std::map<int32_t, ChannelMetrics> channel_metrics;
    std::map<std::string, std::string> descriptor_versions;
    std::map<std::string, bool> descriptor_deprecated;
    std::map<Transport, TransportSnapshot> transport_stats;
    uint64_t queue_overflow_total = 0;
  };

  // Constructs an exporter that will serve on the specified port.
  explicit MetricsExporter(int port = 9308, bool enable_http = true);
  
  ~MetricsExporter();

  // Disable copy and move
  MetricsExporter(const MetricsExporter&) = delete;
  MetricsExporter& operator=(const MetricsExporter&) = delete;

  // Starts the metrics HTTP server.
  // Returns true if started successfully.
  bool Start(bool start_http_server = true);

  // Stops the metrics HTTP server.
  void Stop();

  // Returns true if the exporter is currently running.
  bool IsRunning() const { return running_.load(std::memory_order_acquire); }

  // Updates metrics for a specific channel.
  bool SubmitChannelMetrics(int32_t channel_id, const ChannelMetrics& metrics);

  // Removes metrics for a channel (when channel stops).
  void SubmitChannelRemoval(int32_t channel_id);

  // Registers or updates a metric descriptor with semantic version.
  void RegisterMetricDescriptor(const std::string& name, const std::string& version);

  // Marks a descriptor as deprecated.
  void DeprecateMetricDescriptor(const std::string& name);

  // Records delivery status for a transport.
  void RecordDeliveryStatus(Transport transport, bool success, double latency_ms);

  // P11B-003: Histogram of switch boundary timing delta (ms). Enables p50/p95/p99 analysis.
  void RecordSwitchBoundaryDelta(int32_t channel_id, int64_t delta_ms);

  // P11B-004: Counter of boundary tolerance violations (switch >1 frame late).
  void IncrementBoundaryViolations(int32_t channel_id);

  // P11D-003: Counter of switches that executed at deadline with preview not ready (safety rails).
  void IncrementSwitchDeadlineNotReady(int32_t channel_id);

  // INV-P9-STEADY-005 (P9-CORE-008): Counter of equilibrium violations (depth outside [1,2N] for >1s).
  void IncrementEquilibriumViolations(int32_t channel_id);

  // P9-OPT-002: Steady-state metrics for INV-P9-STEADY-001
  // Sets whether steady-state is active for a channel (gauge: 0 or 1).
  void SetSteadyStateActive(int32_t channel_id, bool active);

  // Records mux CT wait time for histogram (P9-OPT-002).
  void RecordMuxCTWaitMs(int32_t channel_id, double wait_ms);

  // Gets the current metrics for a channel.
  // Returns false if channel doesn't exist.
  bool GetChannelMetrics(int32_t channel_id, ChannelMetrics& metrics) const;

  // Register a supplementary metrics provider that appends Prometheus-format
  // text to /metrics output. Provider must be thread-safe and return valid
  // Prometheus text exposition format. Use for engine-level metrics that live
  // outside the event queue pipeline.
  using CustomMetricsProvider = std::function<std::string()>;
  void RegisterCustomMetricsProvider(const std::string& name, CustomMetricsProvider provider);
  void UnregisterCustomMetricsProvider(const std::string& name);

  // Test helpers.
  Snapshot SnapshotForTest() const;
  bool WaitUntilDrainedForTest(std::chrono::milliseconds timeout);

  uint64_t queue_overflow_total() const { return queue_overflow_total_.load(std::memory_order_acquire); }

 private:
  struct Event {
    enum class Type {
      kUpdateChannel,
      kRemoveChannel,
      kRegisterDescriptor,
      kDeprecateDescriptor,
      kRecordTransport,
      kRecordSwitchBoundaryDelta,
      kIncrementBoundaryViolations,
      kIncrementSwitchDeadlineNotReady,  // P11D-003
      kIncrementEquilibriumViolations,   // INV-P9-STEADY-005
      kSetSteadyStateActive,             // P9-OPT-002
      kRecordMuxCTWaitMs,                // P9-OPT-002
    };

    Type type;
    int32_t channel_id = 0;
    ChannelMetrics channel_metrics;
    std::string descriptor_name;
    std::string descriptor_version;
    Transport transport = Transport::kGrpcStream;
    bool transport_success = true;
    double transport_latency_ms = 0.0;
    int64_t switch_boundary_delta_ms = 0;  // P11B-003
    bool steady_state_active = false;      // P9-OPT-002
    double mux_ct_wait_ms = 0.0;           // P9-OPT-002
  };

  class EventQueue {
   public:
    explicit EventQueue(size_t capacity);

    bool Push(const Event& event);
    bool Pop(Event& event);
    bool Empty() const;

   private:
    const size_t capacity_;
    std::vector<Event> buffer_;
    std::atomic<size_t> head_;
    std::atomic<size_t> tail_;
  };

  // Generates Prometheus-format metrics text.
  std::string GenerateMetricsText() const;

  void WorkerLoop();
  void ProcessEvent(const Event& event);
  static double ComputePercentile(const std::vector<double>& values, double percentile);

  int port_;
  const bool enable_http_;
  std::atomic<bool> running_;
  std::atomic<bool> stop_requested_;
  
  std::unique_ptr<MetricsHTTPServer> http_server_;

  std::atomic<uint64_t> queue_overflow_total_;
  EventQueue event_queue_;
  std::atomic<uint64_t> submitted_events_;
  std::atomic<uint64_t> processed_events_;
  std::mutex queue_mutex_;
  std::condition_variable queue_cv_;
  std::thread worker_thread_;
  
  // Channel metrics storage (protected by mutex)
  mutable std::mutex metrics_mutex_;
  std::map<int32_t, ChannelMetrics> channel_metrics_;
  std::map<std::string, std::string> descriptor_versions_;
  std::map<std::string, bool> descriptor_deprecated_;

  struct TransportData {
    uint64_t deliveries = 0;
    uint64_t failures = 0;
    std::vector<double> latencies_ms;
  };
  std::map<Transport, TransportData> transport_data_;

  // P11B-003/004: Switch boundary timing (INV-BOUNDARY-TOLERANCE-001)
  std::map<int32_t, std::vector<int64_t>> switch_boundary_deltas_ms_;
  std::map<int32_t, uint64_t> switch_boundary_violations_;
  // P11D-003: Switches at deadline with preview not ready (safety rails)
  std::map<int32_t, uint64_t> switch_deadline_not_ready_;
  // INV-P9-STEADY-005: Buffer equilibrium violations (depth outside [1,2N] for >1s)
  std::map<int32_t, uint64_t> equilibrium_violations_;

  // P9-OPT-002: Steady-state metrics (INV-P9-STEADY-001)
  std::map<int32_t, bool> steady_state_active_;                    // gauge: 0 or 1
  std::map<int32_t, int64_t> steady_state_entry_time_us_;          // timestamp of entry
  std::map<int32_t, std::vector<double>> mux_ct_wait_samples_ms_;  // histogram samples

  // Custom metrics providers (appended to /metrics output)
  std::map<std::string, CustomMetricsProvider> custom_providers_;
};

}  // namespace retrovue::telemetry

#endif  // RETROVUE_TELEMETRY_METRICS_EXPORTER_H_

