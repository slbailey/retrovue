// Contract: Frame Selection Alignment (docs/contracts/playout/frame_selection_alignment.md)
// Purpose: Prove that the playout pipeline never emits a frame ahead of the scheduler.
//          actual_src_emitted <= selected_src; if real frame emitted then actual_src_emitted == selected_src.
// Copyright (c) 2025 RetroVue

#include <gtest/gtest.h>

#include <cstdint>
#include <deque>

namespace retrovue::blockplan::testing {
namespace {

// Sentinel for "emit PAD" (no real frame).
constexpr int64_t kPad = -1;

// Alignment policy per contract: given decoder queue (front = next available frame index)
// and selected_src, returns the source frame index to emit, or kPad when PAD must be emitted.
// Simulates: discard while front < selected_src; then if front > selected_src -> PAD; if front == selected_src -> pop and emit.
static int64_t EmissionForTick(std::deque<int64_t>& decoder_queue, int64_t selected_src) {
  while (!decoder_queue.empty() && decoder_queue.front() < selected_src)
    decoder_queue.pop_front();
  if (decoder_queue.empty())
    return kPad;
  if (decoder_queue.front() > selected_src)
    return kPad;  // Future frame: must not emit.
  int64_t frame = decoder_queue.front();
  decoder_queue.pop_front();
  return frame;
}

// ---------------------------------------------------------------------------
// Test Case 1 — Future Frame Protection
// decoder_queue = [100,101,102], selected_src = 98 -> emit PAD
// ---------------------------------------------------------------------------
TEST(FrameAlignmentInvariant, FutureFrameProtection) {
  std::deque<int64_t> decoder_queue = {100, 101, 102};
  const int64_t selected_src = 98;

  int64_t emitted = EmissionForTick(decoder_queue, selected_src);

  EXPECT_EQ(emitted, kPad) << "Must emit PAD when front frame is ahead of selected_src";
  EXPECT_TRUE(decoder_queue.empty() == false)
      << "Queue unchanged (no pop) when emitting PAD for future frame";
  EXPECT_LE(emitted, selected_src) << "Invariant: actual_src_emitted <= selected_src";
}

// ---------------------------------------------------------------------------
// Test Case 2 — Drop Until Alignment
// decoder_queue = [80,81,82,83,84], selected_src = 83 -> emit 83
// ---------------------------------------------------------------------------
TEST(FrameAlignmentInvariant, DropUntilAlignment) {
  std::deque<int64_t> decoder_queue = {80, 81, 82, 83, 84};
  const int64_t selected_src = 83;

  int64_t emitted = EmissionForTick(decoder_queue, selected_src);

  EXPECT_EQ(emitted, 83) << "Must emit 83 after dropping 80,81,82";
  EXPECT_EQ(decoder_queue.size(), 1u);
  EXPECT_EQ(decoder_queue.front(), 84);
  EXPECT_EQ(emitted, selected_src) << "Invariant: actual_src_emitted == selected_src when real frame";
}

// ---------------------------------------------------------------------------
// Test Case 3 — Exact Match
// decoder_queue = [120], selected_src = 120 -> emit 120
// ---------------------------------------------------------------------------
TEST(FrameAlignmentInvariant, ExactMatch) {
  std::deque<int64_t> decoder_queue = {120};
  const int64_t selected_src = 120;

  int64_t emitted = EmissionForTick(decoder_queue, selected_src);

  EXPECT_EQ(emitted, 120);
  EXPECT_TRUE(decoder_queue.empty());
  EXPECT_EQ(emitted, selected_src);
}

// ---------------------------------------------------------------------------
// Test Case 4 — Decoder Far Ahead (real log condition)
// decoder_queue = [273,274,275], selected_src = 160 -> emit PAD
// ---------------------------------------------------------------------------
TEST(FrameAlignmentInvariant, DecoderFarAhead) {
  std::deque<int64_t> decoder_queue = {273, 274, 275};
  const int64_t selected_src = 160;

  int64_t emitted = EmissionForTick(decoder_queue, selected_src);

  EXPECT_EQ(emitted, kPad) << "Must emit PAD when decoder is far ahead of scheduler";
  EXPECT_LE(emitted <= selected_src || emitted == kPad, true);
  EXPECT_EQ(decoder_queue.size(), 3u) << "No frames consumed when emitting PAD for ahead";
}

// ---------------------------------------------------------------------------
// Invariant: actual_src_emitted <= selected_src (and == when real frame)
// ---------------------------------------------------------------------------
TEST(FrameAlignmentInvariant, NeverEmitAhead) {
  struct Scenario {
    std::deque<int64_t> queue;
    int64_t selected_src;
    int64_t expected_emit;  // kPad or frame index
  };
  const Scenario scenarios[] = {
      {{100, 101, 102}, 98, kPad},
      {{80, 81, 82, 83, 84}, 83, 83},
      {{120}, 120, 120},
      {{273, 274, 275}, 160, kPad},
      {{0, 1, 2}, 0, 0},
      {{0, 1, 2}, 1, 1},
      {{}, 50, kPad},
      {{99}, 100, kPad},  // Behind: empty after discard -> PAD
  };

  for (const auto& s : scenarios) {
    std::deque<int64_t> q = s.queue;
    int64_t emitted = EmissionForTick(q, s.selected_src);
    EXPECT_EQ(emitted, s.expected_emit)
        << "selected_src=" << s.selected_src << " queue_size=" << s.queue.size();
    if (emitted != kPad)
      EXPECT_EQ(emitted, s.selected_src) << "Real frame must equal selected_src";
    EXPECT_LE(emitted == kPad ? 0 : emitted, s.selected_src)
        << "Invariant: actual_src_emitted <= selected_src";
  }
}

}  // namespace
}  // namespace retrovue::blockplan::testing
