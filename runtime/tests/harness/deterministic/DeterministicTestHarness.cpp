// Repository: Retrovue-playout
// Component: Deterministic Test Harness Implementation
// Purpose: Orchestrates deterministic testing of AIR control-plane and continuity invariants.
// Copyright (c) 2025 RetroVue

#include "DeterministicTestHarness.h"

#include "retrovue/buffer/FrameRingBuffer.h"
#include "retrovue/runtime/PlayoutControl.h"
#include "retrovue/producers/black/BlackFrameProducer.h"
#include "timing/TestMasterClock.h"

namespace retrovue::tests::harness::deterministic {

DeterministicTestHarness::DeterministicTestHarness()
    : buffer_capacity_(60),
      initial_time_us_(0),
      started_(false),
      live_producer_(nullptr),
      preview_producer_(nullptr) {}

DeterministicTestHarness::~DeterministicTestHarness() {
  if (started_) {
    Stop();
  }
}

void DeterministicTestHarness::RegisterProducerSpec(const std::string& path,
                                                    ProducerSpec spec) {
  producer_specs_[path] = spec;
}

void DeterministicTestHarness::SetBufferCapacity(size_t capacity) {
  buffer_capacity_ = capacity;
}

void DeterministicTestHarness::SetInitialTimeUs(int64_t time_us) {
  initial_time_us_ = time_us;
}

void DeterministicTestHarness::Start() {
  if (started_) {
    return;
  }

  // Create clock in deterministic mode
  clock_ = std::make_shared<timing::TestMasterClock>(
      initial_time_us_, timing::TestMasterClock::Mode::Deterministic);

  // Create buffer
  buffer_ = std::make_unique<buffer::FrameRingBuffer>(buffer_capacity_);

  // Create PlayoutControl
  playout_control_ = std::make_unique<runtime::PlayoutControl>();

  // Set up producer factory that creates fake producers from registered specs
  playout_control_->setProducerFactory(
      [this](const std::string& path,
             const std::string& asset_id,
             buffer::FrameRingBuffer& ring_buffer,
             std::shared_ptr<timing::MasterClock> clock,
             int64_t start_offset_ms,
             int64_t hard_stop_time_ms) {
        return CreateProducer(path, asset_id, ring_buffer, clock,
                              start_offset_ms, hard_stop_time_ms);
      });

  // Configure default program format for fallback producer
  program_format_.video.width = 1920;
  program_format_.video.height = 1080;
  program_format_.video.frame_rate = "30000/1001";
  program_format_.audio.sample_rate = 48000;
  program_format_.audio.channels = 2;

  // Configure the fallback producer in PlayoutControl
  // This enables the real BlackFrameProducer to be used when EnterFallback is called
  playout_control_->ConfigureFallbackProducer(program_format_, *buffer_, clock_);

  // Create and start sink
  sink_ = std::make_unique<RecordingSink>();
  sink_->Start();

  started_ = true;
}

void DeterministicTestHarness::Stop() {
  if (!started_) {
    return;
  }

  // Exit fallback if active
  if (playout_control_ && playout_control_->IsInFallback()) {
    playout_control_->ExitFallback();
  }

  if (sink_) {
    sink_->Stop();
  }

  live_producer_ = nullptr;
  preview_producer_ = nullptr;

  playout_control_.reset();
  buffer_.reset();
  clock_.reset();
  sink_.reset();

  started_ = false;
}

void DeterministicTestHarness::AdvanceTimeUs(int64_t delta_us) {
  if (clock_) {
    clock_->AdvanceMicroseconds(delta_us);
  }
}

void DeterministicTestHarness::AdvanceToNextFrame() {
  AdvanceTimeUs(kFrameIntervalUs);
}

bool DeterministicTestHarness::LoadPreview(const std::string& path,
                                           int64_t start_offset_ms,
                                           int64_t hard_stop_time_ms) {
  if (!started_ || !playout_control_) {
    return false;
  }

  // Generate asset ID from path
  std::string asset_id = "asset:" + path;

  bool result = playout_control_->loadPreviewAsset(
      path, asset_id, *buffer_, clock_, start_offset_ms, hard_stop_time_ms);

  if (result) {
    // Track the preview producer
    const auto& preview_bus = playout_control_->getPreviewBus();
    if (preview_bus.producer) {
      preview_producer_ = dynamic_cast<FakeProducerBase*>(preview_bus.producer.get());
    }
  }

  return result;
}

bool DeterministicTestHarness::SwitchToLive() {
  if (!started_ || !playout_control_) {
    return false;
  }

  bool result = playout_control_->activatePreviewAsLive();

  if (result) {
    // Preview producer moves to live
    live_producer_ = preview_producer_;
    preview_producer_ = nullptr;
  }

  return result;
}

int DeterministicTestHarness::TickProducers() {
  int frames_emitted = 0;
  bool emitted_live_frame = false;

  // Check if we're in fallback mode (via PlayoutControl)
  bool in_fallback = playout_control_->IsInFallback();

  // Tick the live producer if not exhausted and not in fallback
  if (!in_fallback && live_producer_ && live_producer_->isRunning() && !live_producer_->IsExhausted()) {
    if (live_producer_->Tick()) {
      ++frames_emitted;
      emitted_live_frame = true;
    }
  }

  // Check if live producer is exhausted and we need to enter fallback
  if (!in_fallback && live_producer_ && live_producer_->IsExhausted()) {
    // Enter fallback mode with PTS continuity from the live producer
    int64_t continuation_pts = live_producer_->GetCurrentPts();
    playout_control_->EnterFallback(continuation_pts);
    in_fallback = true;
  }

  // Tick the preview producer (shadow decode)
  if (preview_producer_ && preview_producer_->isRunning()) {
    preview_producer_->Tick();
  }

  // If in fallback mode, BlackFrameProducer is running asynchronously.
  // For deterministic testing, we simulate black frame production synchronously
  // using the same asset URI as the real BlackFrameProducer.
  // This allows us to test control-plane invariants without threading complexity.
  if (in_fallback && !emitted_live_frame) {
    // Get current PTS from the fallback producer
    auto* fallback_producer = playout_control_->GetFallbackProducer();
    int64_t black_frame_pts = fallback_producer ? fallback_producer->GetCurrentPts() : 0;

    // Inject a synthetic black frame using the real BlackFrameProducer's asset URI
    buffer::Frame black_frame;
    black_frame.metadata.pts = black_frame_pts;
    black_frame.metadata.dts = black_frame.metadata.pts;
    black_frame.metadata.duration = static_cast<double>(kFrameIntervalUs) / 1'000'000.0;
    black_frame.metadata.asset_uri = producers::black::BlackFrameProducer::kAssetUri;
    black_frame.width = 1;
    black_frame.height = 1;
    black_frame.data.resize(2, 0);

    buffer_->Push(black_frame);
    ++frames_emitted;

    // Advance fallback producer PTS for next frame
    if (fallback_producer) {
      fallback_producer->SetInitialPts(black_frame_pts + kFrameIntervalUs);
    }
  }

  return frames_emitted;
}

int DeterministicTestHarness::DrainBufferToSink() {
  if (!buffer_ || !sink_) {
    return 0;
  }

  int frames_drained = 0;
  buffer::Frame frame;

  while (buffer_->Pop(frame)) {
    sink_->ConsumeVideo(frame);
    ++frames_drained;
  }

  return frames_drained;
}

bool DeterministicTestHarness::IsInBlackFallback() const {
  if (!playout_control_) {
    return false;
  }
  return playout_control_->IsInFallback();
}

uint64_t DeterministicTestHarness::GetFallbackEntryCount() const {
  if (!playout_control_) {
    return 0;
  }
  return playout_control_->GetFallbackEntryCount();
}

RecordingSink& DeterministicTestHarness::GetSink() {
  return *sink_;
}

const RecordingSink& DeterministicTestHarness::GetSink() const {
  return *sink_;
}

std::shared_ptr<timing::TestMasterClock> DeterministicTestHarness::GetClock() const {
  return clock_;
}

buffer::FrameRingBuffer& DeterministicTestHarness::GetBuffer() {
  return *buffer_;
}

FakeProducerBase* DeterministicTestHarness::GetLiveProducer() {
  return live_producer_;
}

FakeProducerBase* DeterministicTestHarness::GetPreviewProducer() {
  return preview_producer_;
}

std::unique_ptr<producers::IProducer> DeterministicTestHarness::CreateProducer(
    const std::string& path,
    const std::string& /*asset_id*/,
    buffer::FrameRingBuffer& ring_buffer,
    std::shared_ptr<timing::MasterClock> clock,
    int64_t /*start_offset_ms*/,
    int64_t hard_stop_time_ms) {

  // Look up the spec for this path
  auto it = producer_specs_.find(path);
  if (it == producer_specs_.end()) {
    // No spec registered - create an infinite producer by default
    // Note: Don't start here - PlayoutControl::loadPreviewAsset will call start()
    return std::make_unique<InfiniteProducer>(
        path, ring_buffer,
        std::dynamic_pointer_cast<timing::TestMasterClock>(clock));
  }

  const auto& spec = it->second;

  // Note: Don't start here - PlayoutControl::loadPreviewAsset will call start()
  switch (spec.type) {
    case ProducerSpec::Type::FINITE:
      return std::make_unique<FiniteProducer>(
          path, ring_buffer,
          std::dynamic_pointer_cast<timing::TestMasterClock>(clock),
          spec.param);

    case ProducerSpec::Type::INFINITE:
      return std::make_unique<InfiniteProducer>(
          path, ring_buffer,
          std::dynamic_pointer_cast<timing::TestMasterClock>(clock));

    case ProducerSpec::Type::CLAMPED: {
      // For clamped producers, use hard_stop_time_ms if provided,
      // otherwise use the spec's param as end_pts
      int64_t end_pts = hard_stop_time_ms > 0
          ? hard_stop_time_ms * 1000  // Convert ms to us
          : spec.param;
      return std::make_unique<ClampedProducer>(
          path, ring_buffer,
          std::dynamic_pointer_cast<timing::TestMasterClock>(clock),
          end_pts);
    }
  }

  return nullptr;
}

}  // namespace retrovue::tests::harness::deterministic
