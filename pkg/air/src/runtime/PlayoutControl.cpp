#include "retrovue/runtime/PlayoutControl.h"

#include <algorithm>
#include <cmath>
#include <iostream>

#include "retrovue/producers/IProducer.h"
#include "retrovue/producers/file/FileProducer.h"
#include "retrovue/producers/black/BlackFrameProducer.h"

namespace retrovue::runtime
{

  namespace
  {

    double MicrosecondsToMilliseconds(int64_t delta_us)
    {
      return static_cast<double>(delta_us) / 1'000.0;
    }

  } // namespace

  PlayoutControl::PlayoutControl()
      : state_(RuntimePhase::kIdle),
        current_pts_us_(0),
        illegal_transition_total_(0),
        latency_violation_total_(0),
        timeout_total_(0),
        queue_overflow_total_(0),
        recover_total_(0),
        consistency_failure_total_(0),
        late_seek_total_(0) {}

  bool PlayoutControl::BeginSession(const std::string &command_id,
                                                int64_t request_utc_us)
  {
    std::lock_guard<std::mutex> lock(mutex_);
    if (!RegisterCommandLocked(command_id))
    {
      return true; // Duplicate command is acknowledged.
    }

    if (state_ != RuntimePhase::kIdle)
    {
      RecordIllegalTransitionLocked(state_, RuntimePhase::kBuffering);
      return false;
    }

    TransitionLocked(RuntimePhase::kBuffering, request_utc_us);
    return true;
  }

  bool PlayoutControl::Pause(const std::string &command_id,
                                         int64_t request_utc_us,
                                         int64_t effective_utc_us,
                                         double boundary_deviation_ms)
  {
    std::lock_guard<std::mutex> lock(mutex_);
    if (!RegisterCommandLocked(command_id))
    {
      return true;
    }

    if (state_ != RuntimePhase::kPlaying)
    {
      RecordIllegalTransitionLocked(state_, RuntimePhase::kPaused);
      return false;
    }

    const double latency_ms =
        MicrosecondsToMilliseconds(effective_utc_us - request_utc_us);
    RecordLatencyLocked(pause_latencies_ms_, latency_ms);
    pause_deviation_ms_.push_back(boundary_deviation_ms);

    if (latency_ms > kPauseLatencyThresholdMs)
    {
      ++latency_violation_total_;
    }

    TransitionLocked(RuntimePhase::kPaused, effective_utc_us);
    return true;
  }

  bool PlayoutControl::Resume(const std::string &command_id,
                                          int64_t request_utc_us,
                                          int64_t effective_utc_us)
  {
    std::lock_guard<std::mutex> lock(mutex_);
    if (!RegisterCommandLocked(command_id))
    {
      return true;
    }

    if (state_ != RuntimePhase::kPaused)
    {
      RecordIllegalTransitionLocked(state_, RuntimePhase::kPlaying);
      return false;
    }

    const double latency_ms =
        MicrosecondsToMilliseconds(effective_utc_us - request_utc_us);
    RecordLatencyLocked(resume_latencies_ms_, latency_ms);
    if (latency_ms > kResumeLatencyThresholdMs)
    {
      ++latency_violation_total_;
    }

    TransitionLocked(RuntimePhase::kPlaying, effective_utc_us);
    return true;
  }

  bool PlayoutControl::Seek(const std::string &command_id,
                                        int64_t request_utc_us,
                                        int64_t target_pts_us,
                                        int64_t effective_utc_us)
  {
    std::lock_guard<std::mutex> lock(mutex_);
    if (!RegisterCommandLocked(command_id))
    {
      return true;
    }

    if (target_pts_us < current_pts_us_)
    {
      ++late_seek_total_;
      return false;
    }

    if (state_ != RuntimePhase::kPlaying && state_ != RuntimePhase::kPaused)
    {
      RecordIllegalTransitionLocked(state_, RuntimePhase::kBuffering);
      return false;
    }

    const double latency_ms =
        MicrosecondsToMilliseconds(effective_utc_us - request_utc_us);
    RecordLatencyLocked(seek_latencies_ms_, latency_ms);
    if (latency_ms > kSeekLatencyThresholdMs)
    {
      ++latency_violation_total_;
    }

    TransitionLocked(RuntimePhase::kBuffering, request_utc_us);
    TransitionLocked(RuntimePhase::kReady, effective_utc_us);
    TransitionLocked(RuntimePhase::kPlaying, effective_utc_us);
    current_pts_us_ = target_pts_us;
    return true;
  }

  bool PlayoutControl::Stop(const std::string &command_id,
                                        int64_t request_utc_us,
                                        int64_t effective_utc_us)
  {
    std::lock_guard<std::mutex> lock(mutex_);
    if (!RegisterCommandLocked(command_id))
    {
      return true;
    }

    if (state_ == RuntimePhase::kIdle)
    {
      RecordIllegalTransitionLocked(state_, RuntimePhase::kStopping);
      return false;
    }

    const double latency_ms =
        MicrosecondsToMilliseconds(effective_utc_us - request_utc_us);
    RecordLatencyLocked(stop_latencies_ms_, latency_ms);
    if (latency_ms > kStopLatencyThresholdMs)
    {
      ++latency_violation_total_;
    }

    TransitionLocked(RuntimePhase::kStopping, request_utc_us);
    TransitionLocked(RuntimePhase::kIdle, effective_utc_us);
    return true;
  }

  bool PlayoutControl::Recover(const std::string &command_id,
                                           int64_t request_utc_us)
  {
    std::lock_guard<std::mutex> lock(mutex_);
    if (!RegisterCommandLocked(command_id))
    {
      return true;
    }

    if (state_ != RuntimePhase::kError)
    {
      RecordIllegalTransitionLocked(state_, RuntimePhase::kBuffering);
      return false;
    }

    TransitionLocked(RuntimePhase::kBuffering, request_utc_us);
    ++recover_total_;
    return true;
  }

  void PlayoutControl::OnBufferDepth(std::size_t depth,
                                                 std::size_t capacity,
                                                 int64_t event_utc_us)
  {
    std::lock_guard<std::mutex> lock(mutex_);
    if (capacity == 0)
    {
      return;
    }

    if (state_ == RuntimePhase::kBuffering && depth >= kReadinessThresholdFrames)
    {
      TransitionLocked(RuntimePhase::kReady, event_utc_us);
      TransitionLocked(RuntimePhase::kPlaying, event_utc_us);
    }
    else if (state_ == RuntimePhase::kPlaying && depth == 0)
    {
      TransitionLocked(RuntimePhase::kBuffering, event_utc_us);
    }
  }

  void PlayoutControl::OnBackPressureEvent(
      TimingLoop::BackPressureEvent event,
      int64_t event_utc_us)
  {
    std::lock_guard<std::mutex> lock(mutex_);
    if (event == TimingLoop::BackPressureEvent::kUnderrun)
    {
      if (state_ == RuntimePhase::kPlaying)
      {
        TransitionLocked(RuntimePhase::kBuffering, event_utc_us);
      }
    }
    else if (event == TimingLoop::BackPressureEvent::kOverrun)
    {
      // Currently treated as informational; no state change but recorded.
      ++queue_overflow_total_;
    }
  }

  void PlayoutControl::OnBackPressureCleared(int64_t event_utc_us)
  {
    std::lock_guard<std::mutex> lock(mutex_);
    if (state_ == RuntimePhase::kBuffering)
    {
      TransitionLocked(RuntimePhase::kReady, event_utc_us);
      TransitionLocked(RuntimePhase::kPlaying, event_utc_us);
    }
  }

  void PlayoutControl::OnExternalTimeout(int64_t event_utc_us)
  {
    std::lock_guard<std::mutex> lock(mutex_);
    ++timeout_total_;
    TransitionLocked(RuntimePhase::kError, event_utc_us);
  }

  void PlayoutControl::OnQueueOverflow()
  {
    std::lock_guard<std::mutex> lock(mutex_);
    ++queue_overflow_total_;
  }

  PlayoutControl::RuntimePhase PlayoutControl::state() const
  {
    std::lock_guard<std::mutex> lock(mutex_);
    return state_;
  }

  PlayoutControl::MetricsSnapshot PlayoutControl::Snapshot()
      const
  {
    std::lock_guard<std::mutex> lock(mutex_);
    MetricsSnapshot snapshot;
    snapshot.transitions = transitions_;
    snapshot.illegal_transition_total = illegal_transition_total_;
    snapshot.latency_violation_total = latency_violation_total_;
    snapshot.timeout_total = timeout_total_;
    snapshot.queue_overflow_total = queue_overflow_total_;
    snapshot.recover_total = recover_total_;
    snapshot.consistency_failure_total = consistency_failure_total_;
    snapshot.late_seek_total = late_seek_total_;
    snapshot.pause_latency_p95_ms = PercentileLocked(pause_latencies_ms_, 0.95);
    snapshot.resume_latency_p95_ms = PercentileLocked(resume_latencies_ms_, 0.95);
    snapshot.seek_latency_p95_ms = PercentileLocked(seek_latencies_ms_, 0.95);
    snapshot.stop_latency_p95_ms = PercentileLocked(stop_latencies_ms_, 0.95);
    snapshot.pause_deviation_p95_ms = PercentileLocked(pause_deviation_ms_, 0.95);
    if (!pause_latencies_ms_.empty())
    {
      snapshot.last_pause_latency_ms = pause_latencies_ms_.back();
    }
    if (!resume_latencies_ms_.empty())
    {
      snapshot.last_resume_latency_ms = resume_latencies_ms_.back();
    }
    if (!seek_latencies_ms_.empty())
    {
      snapshot.last_seek_latency_ms = seek_latencies_ms_.back();
    }
    if (!stop_latencies_ms_.empty())
    {
      snapshot.last_stop_latency_ms = stop_latencies_ms_.back();
    }
    if (!pause_deviation_ms_.empty())
    {
      snapshot.last_pause_deviation_ms = pause_deviation_ms_.back();
    }
    snapshot.state = state_;
    return snapshot;
  }

  void PlayoutControl::TransitionLocked(RuntimePhase to, int64_t event_utc_us)
  {
    if (state_ == to)
    {
      return;
    }
    RecordTransitionLocked(state_, to);
    state_ = to;
    (void)event_utc_us;
  }

  void PlayoutControl::RecordTransitionLocked(RuntimePhase from, RuntimePhase to)
  {
    transitions_[{from, to}]++;
  }

  void PlayoutControl::RecordLatencyLocked(std::vector<double> &samples,
                                                       double value_ms)
  {
    samples.push_back(value_ms);
  }

  double PlayoutControl::PercentileLocked(
      const std::vector<double> &samples,
      double percentile) const
  {
    if (samples.empty())
    {
      return 0.0;
    }

    std::vector<double> copy = samples;
    const double rank = percentile * static_cast<double>(copy.size() - 1);
    const std::size_t lower_index = static_cast<std::size_t>(std::floor(rank));
    const std::size_t upper_index = static_cast<std::size_t>(std::ceil(rank));
    std::nth_element(copy.begin(), copy.begin() + lower_index, copy.end());
    const double lower = copy[lower_index];
    if (upper_index == lower_index)
    {
      return lower;
    }
    std::nth_element(copy.begin(), copy.begin() + upper_index, copy.end());
    const double upper = copy[upper_index];
    const double fraction = rank - static_cast<double>(lower_index);
    return lower + (upper - lower) * fraction;
  }

  bool PlayoutControl::RegisterCommandLocked(
      const std::string &command_id)
  {
    if (command_id.empty())
    {
      return true;
    }
    const auto [it, inserted] = processed_commands_.emplace(command_id, 1);
    if (!inserted)
    {
      return false;
    }
    return true;
  }

  void PlayoutControl::RecordIllegalTransitionLocked(RuntimePhase from,
                                                                RuntimePhase attempted_to)
  {
    ++illegal_transition_total_;
    transitions_[{from, attempted_to}]++;
  }

  void PlayoutControl::setProducerFactory(ProducerFactory factory)
  {
    std::lock_guard<std::mutex> lock(mutex_);
    producer_factory_ = std::move(factory);
  }

  bool PlayoutControl::loadPreviewAsset(const std::string& path,
                                                   const std::string& assetId,
                                                   buffer::FrameRingBuffer& ringBuffer,
                                                   std::shared_ptr<timing::MasterClock> clock,
                                                   int64_t start_offset_ms,
                                                   int64_t hard_stop_time_ms)
  {
    (void)start_offset_ms;
    (void)hard_stop_time_ms;
    std::lock_guard<std::mutex> lock(mutex_);

    // Destroy any existing preview producer before loading a new one
    // This resets shadow decode readiness state (ProducerBus::reset() stops producer)
    if (previewBus.loaded)
    {
      // Reset shadow decode readiness when clearing preview slot
      if (previewBus.producer)
      {
        auto* video_producer = dynamic_cast<producers::file::FileProducer*>(
            previewBus.producer.get());
        if (video_producer)
        {
          // Reset shadow decode state before destroying producer
          video_producer->SetShadowDecodeMode(false); // Clear readiness state
        }
      }
      previewBus.reset();
    }

    // Check if factory is set
    if (!producer_factory_)
    {
      std::cerr << "[PlayoutControl] Producer factory not set" << std::endl;
      return false;
    }

    // Create producer using factory (Phase 6A.1: segment params passed for hard_stop enforcement)
    auto producer = producer_factory_(path, assetId, ringBuffer, clock, start_offset_ms, hard_stop_time_ms);
    if (!producer)
    {
      std::cerr << "[PlayoutControl] Failed to create producer for path: " << path << std::endl;
      return false;
    }

    // Enable shadow decode mode for preview producer
    auto* video_producer = dynamic_cast<producers::file::FileProducer*>(producer.get());
    if (video_producer)
    {
      video_producer->SetShadowDecodeMode(true);
      std::cout << "[PlayoutControl] Enabled shadow decode mode for preview producer" << std::endl;
    }

    // Start producer in shadow mode (decodes but doesn't write to buffer)
    if (!producer->start())
    {
      std::cerr << "[PlayoutControl] Failed to start preview producer" << std::endl;
      return false;
    }

    // Store in preview slot
    previewBus.producer = std::move(producer);
    previewBus.loaded = true;
    previewBus.asset_id = assetId;
    previewBus.file_path = path;

    std::cout << "[PlayoutControl] Loaded preview asset: " << assetId 
              << " from path: " << path << " (shadow decode mode)" << std::endl;
    return true;
  }

  bool PlayoutControl::activatePreviewAsLive(renderer::ProgramOutput* program_output)
  {
    std::lock_guard<std::mutex> lock(mutex_);

    // Check if preview is loaded
    if (!previewBus.loaded || !previewBus.producer)
    {
      std::cerr << "[PlayoutControl] No preview asset loaded to activate" << std::endl;
      return false;
    }

    auto* preview_video_producer = dynamic_cast<producers::file::FileProducer*>(previewBus.producer.get());

    // Phase 6A.1: Simple producer path (e.g. StubProducer) — no shadow decode or PTS alignment
    if (!preview_video_producer)
    {
      std::cout << "[PlayoutControl] Activate preview as live (simple producer)" << std::endl;

      // Exit fallback mode if active (Core is reasserting control)
      if (in_fallback_) {
        std::cout << "[PlayoutControl] Exiting BLACK fallback (control reasserted)" << std::endl;
        if (fallback_producer_) {
          fallback_producer_->stop();
          fallback_producer_.reset();
        }
        in_fallback_ = false;
      }

      if (liveBus.loaded && liveBus.producer && liveBus.producer->isRunning())
        liveBus.producer->stop();
      liveBus.producer = std::move(previewBus.producer);
      liveBus.loaded = true;
      liveBus.asset_id = previewBus.asset_id;
      liveBus.file_path = previewBus.file_path;
      previewBus.reset();
      return true;
    }

    // Check if shadow decode is ready (first frame decoded and cached)
    if (!preview_video_producer->IsShadowDecodeReady())
    {
      std::cerr << "[PlayoutControl] Preview producer shadow decode not ready" << std::endl;
      return false;
    }

    std::cout << "[PlayoutControl] Seamless switch: preview to live..." << std::endl;

    // Exit fallback mode if active (Core is reasserting control)
    if (in_fallback_) {
      std::cout << "[PlayoutControl] Exiting BLACK fallback (control reasserted)" << std::endl;
      if (fallback_producer_) {
        fallback_producer_->stop();
        fallback_producer_.reset();
      }
      in_fallback_ = false;
    }

    // Seamless Switch Algorithm (FileProducer):
    // 1. Get last PTS from live producer. One-tick duration from session/house FPS only
    //    (INV-FPS-RESAMPLE, INV-FPS-TICK-PTS). Never use producer FPS for output PTS step.
    int64_t last_live_pts = 0;
    int64_t frame_duration_us = session_output_fps_.IsValid()
        ? session_output_fps_.FrameDurationUs()
        : retrovue::blockplan::FPS_30.FrameDurationUs();
    if (liveBus.loaded && liveBus.producer && liveBus.producer->isRunning())
    {
      auto* live_video_producer = dynamic_cast<producers::file::FileProducer*>(liveBus.producer.get());
      if (live_video_producer)
      {
        last_live_pts = live_video_producer->GetNextPTS();
        std::cout << "[PlayoutControl] Live producer last PTS: " << last_live_pts << std::endl;
      }
    }

    // 2. Align preview producer PTS to continue from live
    last_pts_step_us_ = frame_duration_us;  // observable for contract tests
    int64_t target_pts = last_live_pts + frame_duration_us;
    preview_video_producer->AlignPTS(target_pts);
    std::cout << "[PlayoutControl] Aligned preview PTS to: " << target_pts << std::endl;

    // 3. Exit shadow mode (preview producer will now write to buffer)
    preview_video_producer->SetShadowDecodeMode(false);
    std::cout << "[PlayoutControl] Preview producer exited shadow mode" << std::endl;

    // 4. Stop the live producer gracefully (wind down)
    if (liveBus.loaded && liveBus.producer && liveBus.producer->isRunning())
    {
      std::cout << "[PlayoutControl] Stopping current live producer gracefully" << std::endl;
      liveBus.producer->stop();
    }

    // 5. Move preview → live (ring buffer writer swap is implicit - preview now writes)
    liveBus.producer = std::move(previewBus.producer);
    liveBus.loaded = true;
    liveBus.asset_id = previewBus.asset_id;
    liveBus.file_path = previewBus.file_path;

    // 6. Reset preview slot as empty
    previewBus.reset();

    // Note: Renderer does NOT reset - it continues reading seamlessly
    // Ring buffer persists through switch with continuous frame stream

    std::cout << "[PlayoutControl] Seamless switch complete. Asset: " 
              << liveBus.asset_id << " (PTS continuous)" << std::endl;
    return true;
  }

  const ProducerBus& PlayoutControl::getPreviewBus() const
  {
    std::lock_guard<std::mutex> lock(mutex_);
    return previewBus;
  }

  const ProducerBus& PlayoutControl::getLiveBus() const
  {
    std::lock_guard<std::mutex> lock(mutex_);
    return liveBus;
  }

  // OutputBus/OutputSink integration (Phase 9.0)
  bool PlayoutControl::CanAttachSink() const
  {
    std::lock_guard<std::mutex> lock(mutex_);
    // Valid states for attach: kReady, kPlaying, kPaused
    // Not valid: kIdle (channel not started), kBuffering (not stable),
    //            kStopping (shutting down), kError (broken)
    switch (state_) {
      case RuntimePhase::kReady:
      case RuntimePhase::kPlaying:
      case RuntimePhase::kPaused:
        return true;
      default:
        return false;
    }
  }

  bool PlayoutControl::CanDetachSink() const
  {
    // Detach is always allowed (forced detach semantics)
    // The contract says: "Detaching a sink leaves OutputBus valid but silent"
    return true;
  }

  void PlayoutControl::OnSinkAttached()
  {
    std::lock_guard<std::mutex> lock(mutex_);
    sink_attached_ = true;
    std::cout << "[PlayoutControl] Sink attached notification received" << std::endl;
  }

  void PlayoutControl::OnSinkDetached()
  {
    std::lock_guard<std::mutex> lock(mutex_);
    sink_attached_ = false;
    std::cout << "[PlayoutControl] Sink detached notification received" << std::endl;
  }

  bool PlayoutControl::IsSinkAttached() const
  {
    std::lock_guard<std::mutex> lock(mutex_);
    return sink_attached_;
  }

  // BlackFrameProducer fallback support

  void PlayoutControl::SetSessionOutputFps(retrovue::blockplan::RationalFps fps)
  {
    std::lock_guard<std::mutex> lock(mutex_);
    session_output_fps_ = fps;
  }

  void PlayoutControl::ConfigureFallbackProducer(const ProgramFormat& format,
                                                 buffer::FrameRingBuffer& buffer,
                                                 std::shared_ptr<timing::MasterClock> clock)
  {
    std::lock_guard<std::mutex> lock(mutex_);
    fallback_format_ = format;
    fallback_buffer_ = &buffer;
    fallback_clock_ = std::move(clock);
    std::cout << "[PlayoutControl] Fallback producer configured: "
              << format.video.width << "x" << format.video.height
              << " @ " << format.GetFrameRateAsDouble() << " fps" << std::endl;
  }

  // ============================================================================
  // FALLBACK STATE MANAGEMENT
  //
  // NOTE: Fallback represents LOSS OF CORE DIRECTION. AIR has run out of content
  // and Core has not yet told us what to do next. This is a dead-man failsafe,
  // not a convenience mechanism.
  //
  // DO NOT exit fallback without an explicit Core command (LoadPreview + SwitchToLive).
  // DO NOT add timers, heuristics, or "helpful" auto-recovery logic here.
  // If you're tempted to make AIR "smarter" about exiting fallback, stop — that
  // violates the architectural boundary. Core owns editorial intent, not AIR.
  // ============================================================================

  bool PlayoutControl::EnterFallback(int64_t continuation_pts_us)
  {
    std::lock_guard<std::mutex> lock(mutex_);

    if (in_fallback_) {
      return false;  // Already in fallback
    }

    if (!fallback_buffer_) {
      std::cerr << "[PlayoutControl] Cannot enter fallback: not configured" << std::endl;
      return false;
    }

    // Stop live producer if running
    if (liveBus.producer && liveBus.producer->isRunning()) {
      std::cout << "[PlayoutControl] Stopping live producer for fallback" << std::endl;
      liveBus.producer->stop();
    }

    // Create and start BlackFrameProducer with PTS continuity
    fallback_producer_ = std::make_unique<producers::black::BlackFrameProducer>(
        *fallback_buffer_, fallback_format_, fallback_clock_, continuation_pts_us);

    if (!fallback_producer_->start()) {
      std::cerr << "[PlayoutControl] Failed to start fallback producer" << std::endl;
      fallback_producer_.reset();
      return false;
    }

    in_fallback_ = true;
    ++fallback_entry_count_;
    std::cout << "[PlayoutControl] Entered BLACK fallback at PTS " << continuation_pts_us
              << " (dead-man failsafe, entry #" << fallback_entry_count_ << ")" << std::endl;
    return true;
  }

  bool PlayoutControl::ExitFallback()
  {
    std::lock_guard<std::mutex> lock(mutex_);

    if (!in_fallback_) {
      return false;  // Not in fallback
    }

    // Stop BlackFrameProducer
    if (fallback_producer_) {
      std::cout << "[PlayoutControl] Stopping fallback producer" << std::endl;
      fallback_producer_->stop();
      fallback_producer_.reset();
    }

    in_fallback_ = false;
    std::cout << "[PlayoutControl] Exited BLACK fallback (control reasserted)" << std::endl;
    return true;
  }

  bool PlayoutControl::IsInFallback() const
  {
    std::lock_guard<std::mutex> lock(mutex_);
    return in_fallback_;
  }

  uint64_t PlayoutControl::GetFallbackEntryCount() const
  {
    std::lock_guard<std::mutex> lock(mutex_);
    return fallback_entry_count_;
  }

  producers::black::BlackFrameProducer* PlayoutControl::GetFallbackProducer() const
  {
    std::lock_guard<std::mutex> lock(mutex_);
    return fallback_producer_.get();
  }

} // namespace retrovue::runtime
