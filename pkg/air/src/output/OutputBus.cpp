// Repository: Retrovue-playout
// Component: OutputBus Implementation
// Purpose: Signal path that routes frames to attached output sinks.
// Copyright (c) 2025 RetroVue

#include "retrovue/output/OutputBus.h"

#include <chrono>
#include <iostream>

#include "retrovue/buffer/FrameRingBuffer.h"
#include "retrovue/runtime/PlayoutControl.h"

namespace retrovue::output {

OutputBus::OutputBus(runtime::PlayoutControl* control)
    : control_(control),
      dbg_bus_heartbeat_time_(std::chrono::steady_clock::now()) {
}

OutputBus::~OutputBus() {
  // Detach any attached sink on destruction
  DetachSink(true);
}

OutputBusResult OutputBus::AttachSink(std::unique_ptr<IOutputSink> sink, bool replace_existing) {
  if (!sink) {
    return OutputBusResult(false, "Cannot attach null sink");
  }

  std::lock_guard<std::mutex> lock(mutex_);

  // Check with control plane if attach is allowed
  if (control_ && !control_->CanAttachSink()) {
    return OutputBusResult(false, "Control plane does not allow sink attachment in current phase");
  }

  // Handle existing sink
  if (sink_) {
    if (!replace_existing) {
      return OutputBusResult(false, "Sink already attached; set replace_existing=true to replace");
    }
    // Stop and detach existing sink
    if (sink_->IsRunning()) {
      sink_->Stop();
    }
    sink_.reset();
    if (control_) {
      control_->OnSinkDetached();
    }
  }

  // Start the new sink
  if (!sink->Start()) {
    return OutputBusResult(false, "Failed to start sink: " + sink->GetName());
  }

  sink_ = std::move(sink);

  // Notify control plane
  if (control_) {
    control_->OnSinkAttached();
  }

  std::cout << "[OutputBus] Sink attached: " << sink_->GetName() << std::endl;
  return OutputBusResult(true, "Sink attached: " + sink_->GetName());
}

OutputBusResult OutputBus::DetachSink(bool force) {
  std::lock_guard<std::mutex> lock(mutex_);

  if (!sink_) {
    return OutputBusResult(true, "No sink attached (idempotent)");
  }

  // Check with control plane if detach is allowed (forced detach always allowed)
  if (!force && control_ && !control_->CanDetachSink()) {
    return OutputBusResult(false, "Control plane does not allow sink detachment in current phase");
  }

  std::string sink_name = sink_->GetName();

  // Stop the sink
  if (sink_->IsRunning()) {
    sink_->Stop();
  }

  sink_.reset();

  // Notify control plane
  if (control_) {
    control_->OnSinkDetached();
  }

  std::cout << "[OutputBus] Sink detached: " << sink_name << std::endl;
  return OutputBusResult(true, "Sink detached: " + sink_name);
}

bool OutputBus::IsAttached() const {
  std::lock_guard<std::mutex> lock(mutex_);
  return sink_ != nullptr;
}

void OutputBus::RouteVideo(const buffer::Frame& frame) {
  std::lock_guard<std::mutex> lock(mutex_);
  dbg_v_routed_.fetch_add(1, std::memory_order_relaxed);

  // =========================================================================
  // INV-P9-SINK-LIVENESS policy enforcement
  // =========================================================================
  // Per SinkLivenessPolicy.md:
  //   - Pre-attach: sink_==nullptr is LEGAL; frames silently discarded
  //   - Post-attach: frames MUST reach sink until explicit DetachSink
  //
  // No warning for pre-attach discard - this is expected "hot standby" behavior.
  // =========================================================================
  if (sink_ && sink_->IsRunning()) {
    sink_->ConsumeVideo(frame);
  }
  // else: Pre-attach or post-detach discard (silent, legal per INV-P9-SINK-LIVENESS-001)
}

void OutputBus::RouteAudio(const buffer::AudioFrame& audio_frame) {
  std::lock_guard<std::mutex> lock(mutex_);
  dbg_a_routed_.fetch_add(1, std::memory_order_relaxed);

  // INV-P9-SINK-LIVENESS: Same policy as RouteVideo
  // Pre-attach/post-detach discard is silent and legal
  if (sink_ && sink_->IsRunning()) {
    sink_->ConsumeAudio(audio_frame);
  }
}

std::string OutputBus::GetAttachedSinkName() const {
  std::lock_guard<std::mutex> lock(mutex_);
  return sink_ ? sink_->GetName() : "";
}

}  // namespace retrovue::output
