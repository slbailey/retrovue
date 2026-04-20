// AIR vNext — BlockRuntime.
//
// AirSession-owned wrapper that pairs an editorial Block record (Core's
// handoff unit) with the runtime state of each of its Segments (AIR's
// playback unit). Per the C1.3 ownership decision:
//
//   - AirSession owns per-block runtime Segment state via a block-runtime
//     wrapper. NOT an AirSession-global (block_id, segment_index) map. NOT
//     SeamController. NOT PrimingPipeline.
//   - PrimingPipeline writes SegmentRuntime state + primed payload via
//     AirSession hooks; SeamController reads readiness via AirSession hooks.
//   - State lives next to the Block it describes; when a queued Block is
//     retired or revised, its runtime state is discarded with it.
//
// Scope in C1.3: BlockRuntime is defined and exercised by the SeamController
// contract tests. AirSession migration from std::optional<Block> /
// std::deque<Block> to BlockRuntime storage happens in C1.4a alongside
// encode-loop wiring, not in this slice (per C1.3 guardrails: no source swap,
// no encode-loop wiring, no block promotion).

#ifndef AIR_BLOCK_RUNTIME_HPP_
#define AIR_BLOCK_RUNTIME_HPP_

#include <cstdint>
#include <memory>
#include <string>
#include <utility>
#include <vector>

#include "block.hpp"
#include "file_source_producer.hpp"
#include "priming_pipeline.hpp"
#include "standard_normalizer.hpp"

namespace retrovue::air {

// Per-Segment runtime state. Parallel to Block.segments — one entry per
// editorial Segment. Lifecycle in C1.3 is limited to the priming surface
// (raw / priming / primed / failed). armed / active / retired runtime
// markers are added once SeamController integrates with AirSession.
struct SegmentRuntime {
  SegmentPrimeState state = SegmentPrimeState::kRaw;
  // Stable reason code iff state == kFailed. Empty otherwise.
  std::string failure_reason;
  // Populated iff state == kPrimed. Ownership lives here until the seam
  // fires and the encode loop takes over (C1.4a).
  std::unique_ptr<FileSourceProducer> source;
  std::unique_ptr<StandardNormalizer> normalizer;
  // JIP lateness in ms applied to this segment at seam fire per
  // INV-SEAM-LATE-SUCCESSOR-JIP-001. Populated when the pad bridge
  // exits and this segment is entered at asset_start_offset_ms +
  // jip_lateness_ms. Consumed at the NEXT seam swap so the PTS offset
  // advances by (duration_ms − jip_lateness_ms), preserving downstream
  // fence alignment.
  int64_t jip_lateness_ms = 0;
};

class BlockRuntime {
 public:
  explicit BlockRuntime(Block block)
      : block_(std::move(block)), runtimes_(block_.segments.size()) {}

  BlockRuntime(const BlockRuntime&) = delete;
  BlockRuntime& operator=(const BlockRuntime&) = delete;
  BlockRuntime(BlockRuntime&&) noexcept = default;
  BlockRuntime& operator=(BlockRuntime&&) noexcept = default;

  const Block& block() const { return block_; }
  const std::string& block_id() const { return block_.block_id; }
  std::size_t segment_count() const { return runtimes_.size(); }

  // Accessors. InvalidIndex returns a reference to a sentinel default
  // SegmentRuntime; callers should bounds-check via segment_count().
  SegmentRuntime& at(int32_t segment_index) { return runtimes_.at(segment_index); }
  const SegmentRuntime& at(int32_t segment_index) const {
    return runtimes_.at(segment_index);
  }

  SegmentPrimeState State(int32_t segment_index) const {
    return runtimes_.at(segment_index).state;
  }

  bool IsPrimed(int32_t segment_index) const {
    return State(segment_index) == SegmentPrimeState::kPrimed;
  }

  // Transition helpers. Deliberately low-level: policy (when to prime,
  // when to fire) lives in PrimingPipeline / SeamController, not here.
  void SetState(int32_t segment_index, SegmentPrimeState s) {
    runtimes_.at(segment_index).state = s;
  }

  void InstallPrimed(int32_t segment_index, PrimedSegment primed) {
    auto& r = runtimes_.at(segment_index);
    r.state = SegmentPrimeState::kPrimed;
    r.source = std::move(primed.source);
    r.normalizer = std::move(primed.normalizer);
    r.failure_reason.clear();
  }

  void RecordFailure(int32_t segment_index, std::string reason) {
    auto& r = runtimes_.at(segment_index);
    r.state = SegmentPrimeState::kFailed;
    r.failure_reason = std::move(reason);
    r.source.reset();
    r.normalizer.reset();
  }

 private:
  Block block_;
  std::vector<SegmentRuntime> runtimes_;
};

}  // namespace retrovue::air

#endif  // AIR_BLOCK_RUNTIME_HPP_
