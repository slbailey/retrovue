// AIR vNext — PrimingPipeline implementation.
//
// See priming_pipeline.hpp for scope. Single-worker structural enforcement
// of INV-SEGMENT-PRIMING-SINGLE-001.

#include "priming_pipeline.hpp"

#include <chrono>
#include <utility>

#include "file_source_producer.hpp"
#include "normalizer.hpp"
#include "standard_normalizer.hpp"

namespace retrovue::air {

namespace {

int64_t NowMonoUs() {
  return std::chrono::duration_cast<std::chrono::microseconds>(
             std::chrono::steady_clock::now().time_since_epoch())
      .count();
}

}  // namespace

const char* ToString(SegmentPrimeState s) {
  switch (s) {
    case SegmentPrimeState::kRaw:     return "raw";
    case SegmentPrimeState::kPriming: return "priming";
    case SegmentPrimeState::kPrimed:  return "primed";
    case SegmentPrimeState::kActive:  return "active";
    case SegmentPrimeState::kRetired: return "retired";
    case SegmentPrimeState::kFailed:  return "failed";
  }
  return "?";
}

const char* ToString(PrimingEventKind k) {
  switch (k) {
    case PrimingEventKind::kStarted:   return "segment.prime_started";
    case PrimingEventKind::kCompleted: return "segment.prime_complete";
    case PrimingEventKind::kFailed:    return "segment.prime_failed";
  }
  return "?";
}

PrimingPipeline::PrimingPipeline(Hooks hooks) : hooks_(std::move(hooks)) {}

PrimingPipeline::~PrimingPipeline() { Stop(); }

void PrimingPipeline::SetEventObserver(PrimingEventObserver obs) {
  observer_ = std::move(obs);
}

void PrimingPipeline::Start() {
  std::lock_guard<std::mutex> lk(mu_);
  if (started_) return;
  started_ = true;
  stop_ = false;
  worker_ = std::thread([this] { WorkerLoop(); });
}

void PrimingPipeline::Kick() {
  std::lock_guard<std::mutex> lk(mu_);
  kicked_ = true;
  cv_.notify_one();
}

void PrimingPipeline::Stop() {
  {
    std::lock_guard<std::mutex> lk(mu_);
    if (!started_) return;
    stop_ = true;
    cv_.notify_all();
  }
  if (worker_.joinable()) worker_.join();
  std::lock_guard<std::mutex> lk(mu_);
  started_ = false;
}

bool PrimingPipeline::RunOnce() {
  auto req = hooks_.next_raw ? hooks_.next_raw() : std::nullopt;
  if (!req.has_value()) return false;
  PrimeOne(*req);
  return true;
}

void PrimingPipeline::WorkerLoop() {
  // Defensive exception boundary (C1.Ops1). FFmpeg bindings used by
  // PrimeOne don't throw; std::make_unique can theoretically throw
  // bad_alloc. A thrown exception out of WorkerLoop would terminate
  // the worker thread silently. Catch, route to on_failed if we have
  // enough context, else drop the pipeline and leave in_progress
  // false so the host can see the worker stopped making progress.
  for (;;) {
    {
      std::unique_lock<std::mutex> lk(mu_);
      cv_.wait(lk, [this] { return stop_ || kicked_; });
      if (stop_) return;
      kicked_ = false;
    }
    // Drain work until next_raw returns nullopt, then wait for next Kick().
    while (true) {
      {
        std::lock_guard<std::mutex> lk(mu_);
        if (stop_) return;
      }
      std::optional<PrimingRequest> req;
      try {
        req = hooks_.next_raw ? hooks_.next_raw() : std::nullopt;
      } catch (...) {
        // next_raw threw. Nothing to route; clear any stale priming
        // flag and wait for the next kick.
        priming_in_progress_.store(false);
        break;
      }
      if (!req.has_value()) break;
      try {
        PrimeOne(*req);
      } catch (...) {
        // PrimeOne threw. Route to on_failed if possible; always
        // clear in-progress so asserts on IsPriming() are honest.
        priming_in_progress_.store(false);
        if (hooks_.on_failed) {
          try {
            hooks_.on_failed(req->block_id, req->segment_index,
                             "PRIME_EXCEPTION");
          } catch (...) {
            // on_failed itself threw. No further routing possible.
          }
        }
      }
    }
  }
}

void PrimingPipeline::Emit(const PrimingEvent& ev) {
  if (observer_) observer_(ev);
}

void PrimingPipeline::PrimeOne(const PrimingRequest& req) {
  // Structural enforcement: only the worker (or RunOnce caller) executes
  // this; single-worker means at most one priming at a time. Flag is the
  // observable signal for tests asserting INV-SEGMENT-PRIMING-SINGLE-001.
  priming_in_progress_.store(true);

  if (hooks_.on_priming) hooks_.on_priming(req.block_id, req.segment_index);

  Emit({.kind = PrimingEventKind::kStarted,
        .mono_us = NowMonoUs(),
        .block_id = req.block_id,
        .segment_index = req.segment_index});

  auto fail = [&](const char* reason) {
    Emit({.kind = PrimingEventKind::kFailed,
          .mono_us = NowMonoUs(),
          .block_id = req.block_id,
          .segment_index = req.segment_index,
          .reason = reason});
    if (hooks_.on_failed) hooks_.on_failed(req.block_id, req.segment_index, reason);
    priming_in_progress_.store(false);
  };

  if (!req.canonical.IsValid()) { fail(kPrimeFailInvalidCanonical); return; }

  auto source = std::make_unique<FileSourceProducer>(
      FileSourceProducer::Config{.file_path = req.asset_uri});

  if (!source->Prepare())  { fail(kPrimeFailAssetOpen); return; }
  if (!source->HasVideoStream() && !source->HasAudioStream()) {
    fail(kPrimeFailNoStreams); return;
  }
  if (!source->Activate()) { fail(kPrimeFailActivate); return; }

  auto normalizer = std::make_unique<StandardNormalizer>(
      req.canonical,
      source->VideoFrameRate(),
      source->VideoWidth(),
      source->VideoHeight(),
      source->AudioSampleRate(),
      source.get(),
      ChannelOrigin{.source_pts_anchor_us = 0, .channel_pts_anchor_us = 0},
      req.samples_per_channel_audio_block);

  Emit({.kind = PrimingEventKind::kCompleted,
        .mono_us = NowMonoUs(),
        .block_id = req.block_id,
        .segment_index = req.segment_index});

  if (hooks_.on_primed) {
    PrimedSegment out;
    out.block_id = req.block_id;
    out.segment_index = req.segment_index;
    out.source = std::move(source);
    out.normalizer = std::move(normalizer);
    hooks_.on_primed(std::move(out));
  }

  priming_in_progress_.store(false);
}

}  // namespace retrovue::air
