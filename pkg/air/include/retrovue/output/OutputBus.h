// Repository: Retrovue-playout
// Component: OutputBus
// Purpose: Non-blocking single-sink router with legal discard semantics.
// Contract: docs/contracts/components/OUTPUTBUS_CONTRACT.md
// Copyright (c) 2025 RetroVue

#ifndef RETROVUE_OUTPUT_OUTPUT_BUS_H_
#define RETROVUE_OUTPUT_OUTPUT_BUS_H_

#include <atomic>
#include <memory>
#include <mutex>
#include <string>

#include "retrovue/output/IOutputSink.h"

namespace retrovue::buffer {
struct Frame;
struct AudioFrame;
}  // namespace retrovue::buffer

namespace retrovue::output {

// Result of an attach/detach operation.
struct OutputBusResult {
  bool success;
  std::string message;

  OutputBusResult(bool s, const std::string& msg) : success(s), message(msg) {}
};

// OutputBus is a non-blocking single-sink router with legal discard semantics.
//
// Contract: docs/contracts/components/OUTPUTBUS_CONTRACT.md
//
// Core Invariants:
//   OB-001: Single sink only (second attach = protocol error)
//   OB-002: Legal discard when unattached (AIR can exist with zero viewers)
//   OB-003: Stable sink between attach/detach (errors don't detach)
//   OB-004: No fan-out, ever (HTTP handles multiplexing)
//   OB-005: No timing or correctness authority
//
// OutputBus explicitly does NOT:
//   - Open sockets or encode media (that's the sink's job)
//   - Make timing or scheduling decisions
//   - Know about viewers or session lifecycle
//   - Ask permission to attach/detach (Core commands, OutputBus executes)
//   - Fan out to multiple consumers
//
// Architectural boundary: OutputBus must never be read directly by clients.
// All fan-out occurs above AIR, via HTTP or equivalent transport.
class OutputBus {
 public:
  OutputBus();
  ~OutputBus();

  // Disable copy and move
  OutputBus(const OutputBus&) = delete;
  OutputBus& operator=(const OutputBus&) = delete;

  // Attaches a sink to this bus.
  // OB-001: If a sink is already attached, this is a PROTOCOL ERROR.
  //         Returns failure. In debug builds, may assert/fatal.
  // Core must detach before attaching a new sink.
  // Thread-safe (serialized with detach, but not in routing hot path).
  OutputBusResult AttachSink(std::unique_ptr<IOutputSink> sink);

  // Detaches the currently attached sink.
  // OB-003: Always succeeds. Core-owned decision.
  // Thread-safe (serialized with attach, but not in routing hot path).
  OutputBusResult DetachSink();

  // Routes a video frame to the attached sink (if any).
  // OB-002: If no sink attached, frame is discarded (legal).
  // OB-005: Non-blocking. Never inspects CT or delays.
  // Called from the render thread.
  // Lock-free in hot path (atomic sink pointer).
  void RouteVideo(const buffer::Frame& frame);

  // Routes an audio frame to the attached sink (if any).
  // Same semantics as RouteVideo.
  void RouteAudio(const buffer::AudioFrame& audio_frame);

  // =========================================================================
  // DIAGNOSTICS ONLY - DO NOT USE FOR EMISSION OR DEQUEUE DECISIONS
  // =========================================================================

  // Returns true if a sink is currently attached.
  // FOR CONTROL PLANE QUERIES ONLY (e.g., to prevent double-attach).
  // DO NOT use for emission gating or routing decisions.
  bool HasSink() const { return sink_.load(std::memory_order_acquire) != nullptr; }

  // Returns discard counts for telemetry.
  uint64_t GetVideoDiscards() const { return discards_video_.load(std::memory_order_relaxed); }
  uint64_t GetAudioDiscards() const { return discards_audio_.load(std::memory_order_relaxed); }

  // Returns the name of the attached sink, or empty string if none attached.
  // FOR LOGGING/DIAGNOSTICS ONLY.
  std::string GetAttachedSinkName() const;

 private:
  // Atomic sink pointer for lock-free routing hot path.
  // Attach/detach use attach_mutex_ for serialization but never contend with routing.
  std::atomic<IOutputSink*> sink_{nullptr};

  // Ownership holder - only touched during attach/detach (under mutex).
  std::unique_ptr<IOutputSink> owned_sink_;

  // Serializes attach/detach operations. NEVER held in routing hot path.
  std::mutex attach_mutex_;

  // Discard counters (OB-002 telemetry)
  std::atomic<uint64_t> discards_video_{0};
  std::atomic<uint64_t> discards_audio_{0};
};

}  // namespace retrovue::output

#endif  // RETROVUE_OUTPUT_OUTPUT_BUS_H_
