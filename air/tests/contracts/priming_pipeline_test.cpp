// AIR vNext — PrimingPipeline contract tests (C1.2).
//
// Validates:
//   - raw → priming → primed happy-path: a real asset (SampleA) can be
//     primed; source + normalizer are delivered; events fire in order.
//   - raw → priming → failed reject-path: a missing asset produces
//     prime_failed with a stable reason code; no source is delivered.
//   - INV-SEGMENT-PRIMING-SINGLE-001: at most one segment is in `priming`
//     state at any sampled moment; sequential processing.
//   - RunOnce() returns false when no raw segments are queued (idle path).
//   - INVALID_CANONICAL rejected without even opening the asset.
//
// Uses a FakeQueue that stands in for AirSession's execution queue. The
// queue tracks per-segment state (block_id, segment_index) → SegmentPrimeState
// and owns the primed source+normalizer on successful prime.

#include <gtest/gtest.h>

#include <atomic>
#include <chrono>
#include <cstdlib>
#include <deque>
#include <filesystem>
#include <map>
#include <memory>
#include <mutex>
#include <string>
#include <thread>
#include <utility>
#include <vector>

#include "channel_canonical.hpp"
#include "file_source_producer.hpp"
#include "priming_pipeline.hpp"
#include "standard_normalizer.hpp"

namespace retrovue::air {
namespace {

std::string ResolveSampleA() {
  if (const char* env = std::getenv("AIR_VNEXT_TEST_MEDIA")) return env;
#ifdef AIR_VNEXT_SAMPLE_A_PATH
  return AIR_VNEXT_SAMPLE_A_PATH;
#else
  return "";
#endif
}

ChannelCanonical CheersCanonical() {
  ChannelCanonical c;
  c.video.width = 968;
  c.video.height = 720;
  c.video.frame_rate = {30000, 1001};
  c.video.pixel_format = PixelFormat::kYuv420p;
  c.audio.sample_rate = 48000;
  c.audio.channels = 2;
  return c;
}

using SegmentKey = std::pair<std::string, int32_t>;

// Fake execution-queue shim. Holds a list of PrimingRequests and a parallel
// map of per-segment state. Hook callbacks mutate the map; tests assert
// against it.
class FakeQueue {
 public:
  void Enqueue(PrimingRequest req) {
    std::lock_guard<std::mutex> lk(mu_);
    states_[{req.block_id, req.segment_index}] = SegmentPrimeState::kRaw;
    pending_.push_back(std::move(req));
  }

  std::optional<PrimingRequest> NextRaw() {
    std::lock_guard<std::mutex> lk(mu_);
    if (pending_.empty()) return std::nullopt;
    PrimingRequest r = std::move(pending_.front());
    pending_.pop_front();
    return r;
  }

  void MarkPriming(const std::string& block_id, int32_t segment_index) {
    std::lock_guard<std::mutex> lk(mu_);
    states_[{block_id, segment_index}] = SegmentPrimeState::kPriming;
  }

  void AcceptPrimed(PrimedSegment seg) {
    std::lock_guard<std::mutex> lk(mu_);
    states_[{seg.block_id, seg.segment_index}] = SegmentPrimeState::kPrimed;
    primed_.push_back(std::move(seg));
  }

  void MarkFailed(const std::string& block_id, int32_t segment_index,
                  const std::string& reason) {
    std::lock_guard<std::mutex> lk(mu_);
    states_[{block_id, segment_index}] = SegmentPrimeState::kFailed;
    failures_[{block_id, segment_index}] = reason;
  }

  SegmentPrimeState State(const std::string& block_id, int32_t segment_index) {
    std::lock_guard<std::mutex> lk(mu_);
    auto it = states_.find({block_id, segment_index});
    return it == states_.end() ? SegmentPrimeState::kRaw : it->second;
  }

  std::string FailureReason(const std::string& block_id, int32_t segment_index) {
    std::lock_guard<std::mutex> lk(mu_);
    auto it = failures_.find({block_id, segment_index});
    return it == failures_.end() ? "" : it->second;
  }

  size_t PrimedCount() {
    std::lock_guard<std::mutex> lk(mu_);
    return primed_.size();
  }

  // Count how many segments are currently in the Priming state. Used to
  // assert INV-SEGMENT-PRIMING-SINGLE-001.
  size_t PrimingCount() {
    std::lock_guard<std::mutex> lk(mu_);
    size_t n = 0;
    for (auto& kv : states_) if (kv.second == SegmentPrimeState::kPriming) ++n;
    return n;
  }

  PrimingPipeline::Hooks Hooks() {
    PrimingPipeline::Hooks h;
    h.next_raw  = [this]                        { return NextRaw(); };
    h.on_priming = [this](auto id, auto idx)    { MarkPriming(id, idx); };
    h.on_primed  = [this](PrimedSegment s)      { AcceptPrimed(std::move(s)); };
    h.on_failed  = [this](auto id, auto idx, auto r) { MarkFailed(id, idx, r); };
    return h;
  }

 private:
  std::mutex mu_;
  std::deque<PrimingRequest> pending_;
  std::map<SegmentKey, SegmentPrimeState> states_;
  std::map<SegmentKey, std::string> failures_;
  std::vector<PrimedSegment> primed_;
};

TEST(PrimingPipelineTest, RunOnceWithNoWorkReturnsFalse) {
  FakeQueue q;
  PrimingPipeline pipe(q.Hooks());
  EXPECT_FALSE(pipe.RunOnce());
}

TEST(PrimingPipelineTest, PrimesSingleValidSegmentToPrimed) {
  const std::string asset = ResolveSampleA();
  if (!std::filesystem::exists(asset)) {
    GTEST_SKIP() << "SampleA not found";
  }

  FakeQueue q;
  PrimingRequest r;
  r.block_id = "block-A";
  r.segment_index = 0;
  r.asset_uri = asset;
  r.asset_start_offset_ms = 0;
  r.canonical = CheersCanonical();
  q.Enqueue(r);
  EXPECT_EQ(q.State("block-A", 0), SegmentPrimeState::kRaw);

  std::vector<PrimingEvent> events;
  std::mutex ev_mu;
  PrimingPipeline pipe(q.Hooks());
  pipe.SetEventObserver([&](const PrimingEvent& e) {
    std::lock_guard<std::mutex> lk(ev_mu);
    events.push_back(e);
  });

  ASSERT_TRUE(pipe.RunOnce());
  EXPECT_EQ(q.State("block-A", 0), SegmentPrimeState::kPrimed);
  EXPECT_EQ(q.PrimedCount(), 1u);

  // Events fire in canonical order: started → complete.
  ASSERT_EQ(events.size(), 2u);
  EXPECT_EQ(events[0].kind, PrimingEventKind::kStarted);
  EXPECT_EQ(events[0].block_id, "block-A");
  EXPECT_EQ(events[0].segment_index, 0);
  EXPECT_EQ(events[1].kind, PrimingEventKind::kCompleted);
  EXPECT_EQ(events[1].block_id, "block-A");

  // No in-flight priming after RunOnce returns.
  EXPECT_FALSE(pipe.IsPriming());
}

TEST(PrimingPipelineTest, MissingAssetMarksFailedWithReason) {
  FakeQueue q;
  PrimingRequest r;
  r.block_id = "block-bad";
  r.segment_index = 2;
  r.asset_uri = "/no/such/asset/absolutely_missing.mp4";
  r.canonical = CheersCanonical();
  q.Enqueue(r);

  std::vector<PrimingEvent> events;
  PrimingPipeline pipe(q.Hooks());
  pipe.SetEventObserver([&](const PrimingEvent& e) { events.push_back(e); });

  ASSERT_TRUE(pipe.RunOnce());
  EXPECT_EQ(q.State("block-bad", 2), SegmentPrimeState::kFailed);
  EXPECT_EQ(q.FailureReason("block-bad", 2), kPrimeFailAssetOpen);
  EXPECT_EQ(q.PrimedCount(), 0u);

  // started → failed. No complete event.
  ASSERT_EQ(events.size(), 2u);
  EXPECT_EQ(events[0].kind, PrimingEventKind::kStarted);
  EXPECT_EQ(events[1].kind, PrimingEventKind::kFailed);
  EXPECT_EQ(events[1].reason, kPrimeFailAssetOpen);
  EXPECT_EQ(events[1].segment_index, 2);
}

TEST(PrimingPipelineTest, InvalidCanonicalRejectedBeforeAssetOpen) {
  FakeQueue q;
  PrimingRequest r;
  r.block_id = "block-bc";
  r.segment_index = 0;
  r.asset_uri = "/no/such/file";  // asset is never opened; canonical check first
  // canonical left default (width=0) → invalid.
  q.Enqueue(r);

  PrimingPipeline pipe(q.Hooks());
  ASSERT_TRUE(pipe.RunOnce());
  EXPECT_EQ(q.State("block-bc", 0), SegmentPrimeState::kFailed);
  EXPECT_EQ(q.FailureReason("block-bc", 0), kPrimeFailInvalidCanonical);
}

TEST(PrimingPipelineTest, WorkerThreadProcessesKickedBatchSequentially) {
  // INV-SEGMENT-PRIMING-SINGLE-001: with two raw segments queued and the
  // worker running, processing happens sequentially. Structural single-
  // worker enforcement — at any sampled moment, PrimingCount() <= 1.
  const std::string asset = ResolveSampleA();
  if (!std::filesystem::exists(asset)) {
    GTEST_SKIP() << "SampleA not found";
  }

  FakeQueue q;
  for (int i = 0; i < 2; ++i) {
    PrimingRequest r;
    r.block_id = "block-A";
    r.segment_index = i;
    r.asset_uri = asset;
    r.canonical = CheersCanonical();
    q.Enqueue(r);
  }

  std::atomic<int> completed{0};
  std::atomic<size_t> max_concurrent_priming{0};
  std::mutex ev_mu;
  std::vector<PrimingEvent> events;

  PrimingPipeline pipe(q.Hooks());
  pipe.SetEventObserver([&](const PrimingEvent& e) {
    {
      std::lock_guard<std::mutex> lk(ev_mu);
      events.push_back(e);
    }
    // Sample priming count from the event thread. Every kStarted should
    // observe exactly 1 priming; kCompleted / kFailed may observe 0 or 1
    // depending on ordering with the priming_in_progress flag.
    size_t now = q.PrimingCount();
    size_t prev = max_concurrent_priming.load();
    while (now > prev && !max_concurrent_priming.compare_exchange_weak(prev, now)) {}
    if (e.kind == PrimingEventKind::kCompleted ||
        e.kind == PrimingEventKind::kFailed) {
      completed.fetch_add(1);
    }
  });

  pipe.Start();
  pipe.Kick();

  // Wait up to 30s for both segments to complete.
  const auto deadline = std::chrono::steady_clock::now() +
                        std::chrono::seconds(30);
  while (completed.load() < 2 &&
         std::chrono::steady_clock::now() < deadline) {
    std::this_thread::sleep_for(std::chrono::milliseconds(10));
  }
  pipe.Stop();

  EXPECT_EQ(completed.load(), 2);
  EXPECT_EQ(q.State("block-A", 0), SegmentPrimeState::kPrimed);
  EXPECT_EQ(q.State("block-A", 1), SegmentPrimeState::kPrimed);
  EXPECT_EQ(q.PrimedCount(), 2u);
  // Single-worker invariant: at most one segment priming at a sampled moment.
  EXPECT_LE(max_concurrent_priming.load(), 1u);

  // Events: 2 started + 2 complete = 4 total, and their (block_id,
  // segment_index) order interleaves start→complete per segment.
  ASSERT_EQ(events.size(), 4u);
  EXPECT_EQ(events[0].kind, PrimingEventKind::kStarted);
  EXPECT_EQ(events[1].kind, PrimingEventKind::kCompleted);
  EXPECT_EQ(events[2].kind, PrimingEventKind::kStarted);
  EXPECT_EQ(events[3].kind, PrimingEventKind::kCompleted);
}

TEST(PrimingPipelineTest, StopJoinsCleanlyWhenNoWorkWasEverSubmitted) {
  FakeQueue q;
  PrimingPipeline pipe(q.Hooks());
  pipe.Start();
  // No Kick(), no work. Stop must still return cleanly.
  pipe.Stop();
  SUCCEED();
}

TEST(PrimingPipelineTest, StopIsIdempotent) {
  FakeQueue q;
  PrimingPipeline pipe(q.Hooks());
  pipe.Start();
  pipe.Stop();
  pipe.Stop();  // second call is a no-op
  SUCCEED();
}

}  // namespace
}  // namespace retrovue::air
