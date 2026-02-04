// Repository: Retrovue-playout
// Component: OutputBus Implementation
// Purpose: Non-blocking single-sink router with legal discard semantics.
// Contract: docs/contracts/components/OUTPUTBUS_CONTRACT.md
// Copyright (c) 2025 RetroVue

#include "retrovue/output/OutputBus.h"

#include <iostream>

#include "retrovue/buffer/FrameRingBuffer.h"

namespace retrovue::output {

OutputBus::OutputBus() = default;

OutputBus::~OutputBus() {
  // Detach any attached sink on destruction.
  // This is safe because destructor is single-threaded.
  DetachSink();
}

OutputBusResult OutputBus::AttachSink(std::unique_ptr<IOutputSink> sink) {
  if (!sink) {
    return OutputBusResult(false, "Cannot attach null sink");
  }

  std::lock_guard<std::mutex> lock(attach_mutex_);

  // OB-001: Single sink only. Second attach = protocol error.
  // Core must detach before attaching a new sink.
  if (sink_.load(std::memory_order_acquire) != nullptr) {
    return OutputBusResult(false,
        "PROTOCOL ERROR: Sink already attached. "
        "Core must call DetachSink() before attaching a new sink (OB-001)");
  }

  // Start the new sink before making it visible to routing.
  if (!sink->Start()) {
    return OutputBusResult(false, "Failed to start sink: " + sink->GetName());
  }

  std::string sink_name = sink->GetName();

  // Transfer ownership and make visible to routing.
  // Order matters: owned_sink_ must hold ownership before atomic publish.
  owned_sink_ = std::move(sink);
  sink_.store(owned_sink_.get(), std::memory_order_release);

  std::cout << "[OutputBus] Sink attached: " << sink_name << std::endl;
  return OutputBusResult(true, "Sink attached: " + sink_name);
}

OutputBusResult OutputBus::DetachSink() {
  std::lock_guard<std::mutex> lock(attach_mutex_);

  // OB-003: Detach is always explicit and Core-owned. Always succeeds.
  IOutputSink* current = sink_.load(std::memory_order_acquire);
  if (!current) {
    return OutputBusResult(true, "No sink attached (idempotent)");
  }

  std::string sink_name = current->GetName();

  // Make sink invisible to routing FIRST (atomic null).
  // After this store, routing threads will discard instead of routing.
  sink_.store(nullptr, std::memory_order_release);

  // Now safe to stop and destroy - no routing thread can reach it.
  if (owned_sink_ && owned_sink_->IsRunning()) {
    owned_sink_->Stop();
  }
  owned_sink_.reset();

  std::cout << "[OutputBus] Sink detached: " << sink_name << std::endl;
  return OutputBusResult(true, "Sink detached: " + sink_name);
}

void OutputBus::RouteVideo(const buffer::Frame& frame) {
  // OB-005: Lock-free hot path. No mutex, no delay, no retry.
  // Atomic load provides acquire semantics for sink pointer.
  IOutputSink* sink = sink_.load(std::memory_order_acquire);

  if (sink && sink->IsRunning()) {
    // OB-003: Post-attach, every frame reaches the sink.
    sink->ConsumeVideo(frame);
  } else {
    // OB-002: Legal discard when unattached.
    // This is correct behavior, not an error.
    discards_video_.fetch_add(1, std::memory_order_relaxed);
  }
}

void OutputBus::RouteAudio(const buffer::AudioFrame& audio_frame) {
  // OB-005: Lock-free hot path. Same semantics as RouteVideo.
  IOutputSink* sink = sink_.load(std::memory_order_acquire);

  if (sink && sink->IsRunning()) {
    sink->ConsumeAudio(audio_frame);
  } else {
    // OB-002: Legal discard when unattached.
    discards_audio_.fetch_add(1, std::memory_order_relaxed);
  }
}

std::string OutputBus::GetAttachedSinkName() const {
  // FOR DIAGNOSTICS ONLY - not for routing or gating decisions.
  IOutputSink* sink = sink_.load(std::memory_order_acquire);
  return sink ? sink->GetName() : "";
}

}  // namespace retrovue::output
