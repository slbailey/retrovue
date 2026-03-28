// Repository: Retrovue-playout
// Component: Decode Result Model Contract Tests
// Purpose: Enforce INV-AIR-DECODE-RESULT-*-001 invariants from
//          docs/contracts/air/DECODE_RESULT_MODEL.md
//
// These tests define the behavioral truth for the in-band decode result
// model. They are written BEFORE the production interface change.
//
// COMPILATION NOTE:
// These tests define a local DecodeStatus/DecodeResult that mirrors the
// contract-specified types. When the production ITickProducer interface
// is updated, the local types are replaced with production imports.
// Until then, these tests validate the mock contract independently.
//
// Invariants under test:
//   INV-AIR-DECODE-RESULT-EXPLICIT-001 — explicit status on every decode
//   INV-AIR-EOF-NON-REPEATABLE-001     — kEof → pad, never repeat
//   INV-AIR-UNDERRUN-REPEATABLE-001    — kUnderrun → repeat allowed
//   INV-AIR-ERROR-FAILSAFE-001         — kError → pad failsafe
//   INV-AIR-DECODE-RESULT-SCOPE-001    — status per-call, no cross-segment
//   INV-AIR-EOF-PAD-TRANSITION-001     — commercial → pad transition
//
// Copyright (c) 2026 RetroVue

#include <gtest/gtest.h>

#include <cstdint>
#include <cstring>
#include <optional>
#include <string>
#include <vector>

#include "retrovue/buffer/FrameRingBuffer.h"

namespace retrovue::blockplan::testing {
namespace {

// =============================================================================
// CONTRACT-SPECIFIED TYPES (local until production interface updated)
// These MUST match docs/contracts/air/DECODE_RESULT_MODEL.md exactly.
// =============================================================================

enum class DecodeStatus {
  kFrame,     // Normal decoded frame available
  kUnderrun,  // Temporary — no frame this tick, may recover
  kEof,       // Terminal — segment asset exhausted, no more frames
  kError      // Fatal — decoder failed, unrecoverable for this segment
};

// Forward declaration — FrameData is defined in TickProducer.hpp.
// For test isolation, we define a minimal local version.
struct TestFrameData {
  buffer::Frame video;
  std::string asset_uri;
  int64_t block_ct_ms = 0;
  int64_t source_frame_index = -1;
  std::vector<buffer::AudioFrame> audio;
};

struct DecodeResult {
  DecodeStatus status;
  std::optional<TestFrameData> frame;  // present when status == kFrame
};

// =============================================================================
// Helpers — frame construction and verification
// =============================================================================

static constexpr uint8_t kContentY = 0x30;  // Distinguishable from pad
static constexpr uint8_t kPadY = 0x10;      // Broadcast black

static buffer::Frame MakeVideoFrame(int width, int height, uint8_t y_fill) {
  buffer::Frame frame;
  frame.width = width;
  frame.height = height;
  int y_size = width * height;
  int uv_size = (width / 2) * (height / 2);
  frame.data.resize(static_cast<size_t>(y_size + 2 * uv_size));
  std::memset(frame.data.data(), y_fill, static_cast<size_t>(y_size));
  std::memset(frame.data.data() + y_size, 0x80,
              static_cast<size_t>(2 * uv_size));
  return frame;
}

static buffer::Frame MakePadFrame(int width, int height) {
  return MakeVideoFrame(width, height, kPadY);
}

static buffer::AudioFrame MakeSilence(int nb_samples) {
  buffer::AudioFrame frame;
  frame.sample_rate = buffer::kHouseAudioSampleRate;
  frame.channels = buffer::kHouseAudioChannels;
  frame.nb_samples = nb_samples;
  frame.data.resize(
      static_cast<size_t>(nb_samples * buffer::kHouseAudioChannels) *
      sizeof(int16_t), 0);
  return frame;
}

static bool IsPadFrame(const buffer::Frame& f) {
  return !f.data.empty() && f.data[0] == kPadY;
}

static bool IsContentFrame(const buffer::Frame& f) {
  return !f.data.empty() && f.data[0] == kContentY;
}

// =============================================================================
// DecodeResult factory helpers
// =============================================================================

static DecodeResult Frame(int width, int height, int64_t frame_index) {
  TestFrameData fd;
  fd.video = MakeVideoFrame(width, height, kContentY);
  fd.asset_uri = "commercial.mp4";
  fd.block_ct_ms = frame_index * 33;
  fd.source_frame_index = frame_index;
  fd.audio.push_back(MakeSilence(1024));
  return DecodeResult{DecodeStatus::kFrame, std::move(fd)};
}

static DecodeResult Underrun() {
  return DecodeResult{DecodeStatus::kUnderrun, std::nullopt};
}

static DecodeResult Eof() {
  return DecodeResult{DecodeStatus::kEof, std::nullopt};
}

static DecodeResult Error() {
  return DecodeResult{DecodeStatus::kError, std::nullopt};
}

// =============================================================================
// ScriptedMockProducer
//
// Returns a pre-defined sequence of DecodeResult values.
// Each call to Produce() returns the next result in the script.
// After the script is exhausted, returns kEof.
// =============================================================================

class ScriptedMockProducer {
 public:
  explicit ScriptedMockProducer(std::vector<DecodeResult> script)
      : script_(std::move(script)) {}

  DecodeResult Produce() {
    if (pos_ < static_cast<int>(script_.size())) {
      return std::move(script_[pos_++]);
    }
    return Eof();
  }

  int position() const { return pos_; }

 private:
  std::vector<DecodeResult> script_;
  int pos_ = 0;
};

// =============================================================================
// FillLoopSimulator
//
// Simulates the VideoLookaheadBuffer fill loop's policy decisions
// as specified in DECODE_RESULT_MODEL.md § Behavioral Matrix.
//
// This is the CONTRACTUAL behavior. When the production fill loop
// is updated, it must produce identical results for these inputs.
// =============================================================================

struct BufferFrame {
  buffer::Frame video;
  bool was_decoded;
  std::string asset_uri;
};

class FillLoopSimulator {
 public:
  FillLoopSimulator(int width, int height)
      : width_(width), height_(height),
        pad_frame_(MakePadFrame(width, height)) {}

  // Simulate one fill-loop iteration given a DecodeResult.
  // Returns the frame that would be pushed to the buffer.
  BufferFrame ProcessResult(const DecodeResult& result) {
    BufferFrame bf;

    switch (result.status) {
      case DecodeStatus::kFrame:
        // Normal: push decoded frame.
        bf.video = result.frame->video;
        bf.was_decoded = true;
        bf.asset_uri = result.frame->asset_uri;
        last_decoded_ = result.frame->video;
        have_last_ = true;
        in_gap_ = false;
        break;

      case DecodeStatus::kUnderrun:
        // Transient: hold last frame. NOT pad.
        // INV-AIR-UNDERRUN-REPEATABLE-001
        if (have_last_) {
          bf.video = last_decoded_;
        } else {
          bf.video = pad_frame_;  // no prior frame → pad fallback
        }
        bf.was_decoded = false;
        bf.asset_uri = "";
        in_gap_ = true;
        break;

      case DecodeStatus::kEof:
        // Terminal: pad frame. NEVER hold last.
        // INV-AIR-EOF-NON-REPEATABLE-001
        bf.video = pad_frame_;
        bf.was_decoded = false;
        bf.asset_uri = "";
        in_gap_ = true;
        break;

      case DecodeStatus::kError:
        // Fatal: pad frame. Same as EOF for emission.
        // INV-AIR-ERROR-FAILSAFE-001
        bf.video = pad_frame_;
        bf.was_decoded = false;
        bf.asset_uri = "";
        in_gap_ = true;
        break;
    }

    return bf;
  }

  bool in_gap() const { return in_gap_; }

 private:
  int width_;
  int height_;
  buffer::Frame pad_frame_;
  buffer::Frame last_decoded_;
  bool have_last_ = false;
  bool in_gap_ = false;
};

}  // namespace

// =============================================================================
// INV-AIR-DECODE-RESULT-EXPLICIT-001
// Every TryGetFrame return has an explicit DecodeStatus.
// =============================================================================

TEST(DecodeResultModel, TEST_INV_DECODE_RESULT_EXPLICIT_001) {
  // Contract: no DecodeResult may have an ambiguous status.
  // Verify that every factory function produces a well-defined status.

  auto frame_result = Frame(720, 480, 0);
  EXPECT_EQ(frame_result.status, DecodeStatus::kFrame);
  EXPECT_TRUE(frame_result.frame.has_value());

  auto underrun_result = Underrun();
  EXPECT_EQ(underrun_result.status, DecodeStatus::kUnderrun);
  EXPECT_FALSE(underrun_result.frame.has_value());

  auto eof_result = Eof();
  EXPECT_EQ(eof_result.status, DecodeStatus::kEof);
  EXPECT_FALSE(eof_result.frame.has_value());

  auto error_result = Error();
  EXPECT_EQ(error_result.status, DecodeStatus::kError);
  EXPECT_FALSE(error_result.frame.has_value());

  // Verify: no status value is default-constructed or uninitialized.
  // The enum is exhaustive — switch on it must cover all cases.
  int covered = 0;
  for (auto s : {DecodeStatus::kFrame, DecodeStatus::kUnderrun,
                 DecodeStatus::kEof, DecodeStatus::kError}) {
    switch (s) {
      case DecodeStatus::kFrame:    covered++; break;
      case DecodeStatus::kUnderrun: covered++; break;
      case DecodeStatus::kEof:      covered++; break;
      case DecodeStatus::kError:    covered++; break;
    }
  }
  EXPECT_EQ(covered, 4) << "All four status values must be coverable";
}

// =============================================================================
// INV-AIR-EOF-NON-REPEATABLE-001
// kEof must produce pad frames, never repeated last frame.
// =============================================================================

TEST(DecodeResultModel, TEST_INV_EOF_NON_REPEATABLE_001) {
  // Script: 10 content frames, then EOF.
  std::vector<DecodeResult> script;
  for (int i = 0; i < 10; ++i) {
    script.push_back(Frame(720, 480, i));
  }
  script.push_back(Eof());
  script.push_back(Eof());
  script.push_back(Eof());

  ScriptedMockProducer producer(std::move(script));
  FillLoopSimulator sim(720, 480);

  // Process content frames.
  for (int i = 0; i < 10; ++i) {
    auto result = producer.Produce();
    auto bf = sim.ProcessResult(result);
    ASSERT_TRUE(IsContentFrame(bf.video))
        << "Frame " << i << " should be content";
    EXPECT_TRUE(bf.was_decoded);
  }

  // Process EOF frames — MUST be pad, NEVER content.
  for (int i = 0; i < 3; ++i) {
    auto result = producer.Produce();
    ASSERT_EQ(result.status, DecodeStatus::kEof);
    auto bf = sim.ProcessResult(result);

    // INV-AIR-EOF-NON-REPEATABLE-001: MUST be pad.
    EXPECT_TRUE(IsPadFrame(bf.video))
        << "Post-EOF frame " << i << " MUST be pad (black), not held content";
    EXPECT_FALSE(bf.was_decoded);

    // NEGATIVE ASSERTION: Must NOT be the last content frame.
    EXPECT_FALSE(IsContentFrame(bf.video))
        << "Post-EOF frame " << i << " MUST NOT be repeated content (Y=0x30)";
  }
}

// =============================================================================
// INV-AIR-UNDERRUN-REPEATABLE-001
// kUnderrun must hold last frame, not emit pad.
// =============================================================================

TEST(DecodeResultModel, TEST_INV_UNDERRUN_REPEATABLE_001) {
  // Script: 5 content frames, then 3 underruns, then 2 more content.
  std::vector<DecodeResult> script;
  for (int i = 0; i < 5; ++i) {
    script.push_back(Frame(720, 480, i));
  }
  script.push_back(Underrun());
  script.push_back(Underrun());
  script.push_back(Underrun());
  for (int i = 5; i < 7; ++i) {
    script.push_back(Frame(720, 480, i));
  }

  ScriptedMockProducer producer(std::move(script));
  FillLoopSimulator sim(720, 480);

  // Process content.
  for (int i = 0; i < 5; ++i) {
    auto result = producer.Produce();
    auto bf = sim.ProcessResult(result);
    ASSERT_TRUE(IsContentFrame(bf.video));
  }

  // Process underruns — MUST hold last frame, MUST NOT emit pad.
  for (int i = 0; i < 3; ++i) {
    auto result = producer.Produce();
    ASSERT_EQ(result.status, DecodeStatus::kUnderrun);
    auto bf = sim.ProcessResult(result);

    // INV-AIR-UNDERRUN-REPEATABLE-001: MUST be held frame (content), NOT pad.
    EXPECT_TRUE(IsContentFrame(bf.video))
        << "Underrun frame " << i << " MUST be held content, not pad";
    EXPECT_FALSE(bf.was_decoded)
        << "Held frame should have was_decoded=false";

    // NEGATIVE ASSERTION: Must NOT be pad.
    EXPECT_FALSE(IsPadFrame(bf.video))
        << "Underrun frame " << i << " MUST NOT be pad (would cause black flash)";
  }

  // Recovery: content resumes.
  for (int i = 0; i < 2; ++i) {
    auto result = producer.Produce();
    ASSERT_EQ(result.status, DecodeStatus::kFrame);
    auto bf = sim.ProcessResult(result);
    EXPECT_TRUE(IsContentFrame(bf.video));
    EXPECT_TRUE(bf.was_decoded);
  }
}

// =============================================================================
// INV-AIR-ERROR-FAILSAFE-001
// kError must produce pad frames, identical to kEof behavior.
// =============================================================================

TEST(DecodeResultModel, TEST_INV_ERROR_FAILSAFE_001) {
  // Script: 3 content frames, then error.
  std::vector<DecodeResult> script;
  for (int i = 0; i < 3; ++i) {
    script.push_back(Frame(720, 480, i));
  }
  script.push_back(Error());
  script.push_back(Error());

  ScriptedMockProducer producer(std::move(script));
  FillLoopSimulator sim(720, 480);

  // Content.
  for (int i = 0; i < 3; ++i) {
    auto result = producer.Produce();
    sim.ProcessResult(result);
  }

  // Error — MUST be pad, MUST NOT be corrupted or undefined.
  for (int i = 0; i < 2; ++i) {
    auto result = producer.Produce();
    ASSERT_EQ(result.status, DecodeStatus::kError);
    auto bf = sim.ProcessResult(result);

    EXPECT_TRUE(IsPadFrame(bf.video))
        << "Error frame " << i << " MUST be pad (black)";
    EXPECT_FALSE(bf.was_decoded);
    EXPECT_FALSE(bf.video.data.empty())
        << "Error frame MUST NOT have empty data (undefined/corrupted)";
  }
}

// =============================================================================
// INV-AIR-DECODE-RESULT-SCOPE-001
// Status is per-call. EOF on segment A does not affect segment B.
// =============================================================================

TEST(DecodeResultModel, TEST_INV_DECODE_RESULT_SCOPE_001) {
  // Simulate two segments using two independent producers.
  // Segment A: 5 frames then EOF.
  // Segment B: 5 frames (no EOF).
  // EOF on A must NOT cause B to emit pad.

  // Segment A.
  std::vector<DecodeResult> script_a;
  for (int i = 0; i < 5; ++i) {
    script_a.push_back(Frame(720, 480, i));
  }
  script_a.push_back(Eof());

  ScriptedMockProducer producer_a(std::move(script_a));
  FillLoopSimulator sim_a(720, 480);

  for (int i = 0; i < 5; ++i) {
    sim_a.ProcessResult(producer_a.Produce());
  }
  // EOF on A.
  auto eof_result = producer_a.Produce();
  ASSERT_EQ(eof_result.status, DecodeStatus::kEof);
  auto bf_eof = sim_a.ProcessResult(eof_result);
  EXPECT_TRUE(IsPadFrame(bf_eof.video)) << "A's EOF must produce pad";

  // Segment B — INDEPENDENT producer, fresh state.
  std::vector<DecodeResult> script_b;
  for (int i = 0; i < 5; ++i) {
    script_b.push_back(Frame(720, 480, i + 100));
  }

  ScriptedMockProducer producer_b(std::move(script_b));
  FillLoopSimulator sim_b(720, 480);  // Fresh simulator — no inherited state.

  // B must produce content, NOT pad.
  for (int i = 0; i < 5; ++i) {
    auto result = producer_b.Produce();
    ASSERT_EQ(result.status, DecodeStatus::kFrame)
        << "Segment B frame " << i << " must be kFrame, not inherited kEof";
    auto bf = sim_b.ProcessResult(result);
    EXPECT_TRUE(IsContentFrame(bf.video))
        << "Segment B frame " << i << " must be content, not pad from A's EOF";
    EXPECT_TRUE(bf.was_decoded);
  }
}

// =============================================================================
// INV-AIR-EOF-PAD-TRANSITION-001 (CommercialToPad full scenario)
// Commercial shorter than allocated slot → remaining duration is pad.
// =============================================================================

TEST(DecodeResultModel, TEST_INV_EOF_PAD_TRANSITION_CommercialToPad) {
  // Commercial: 1821 content frames, then 65 frames of EOF tail.
  // Contract: after content exhaustion, ALL remaining frames are pad.
  const int commercial_frames = 1821;
  const int pad_tail_frames = 65;

  std::vector<DecodeResult> script;
  for (int i = 0; i < commercial_frames; ++i) {
    script.push_back(Frame(720, 480, i));
  }
  for (int i = 0; i < pad_tail_frames; ++i) {
    script.push_back(Eof());
  }

  ScriptedMockProducer producer(std::move(script));
  FillLoopSimulator sim(720, 480);

  // Play commercial.
  for (int i = 0; i < commercial_frames; ++i) {
    auto result = producer.Produce();
    auto bf = sim.ProcessResult(result);
    ASSERT_TRUE(IsContentFrame(bf.video)) << "Commercial frame " << i;
  }

  // EOF tail — ALL must be pad, NO freeze frames.
  int pad_count = 0;
  int content_count = 0;
  for (int i = 0; i < pad_tail_frames; ++i) {
    auto result = producer.Produce();
    ASSERT_EQ(result.status, DecodeStatus::kEof)
        << "Tail frame " << i << " must report kEof";
    auto bf = sim.ProcessResult(result);

    if (IsPadFrame(bf.video)) {
      pad_count++;
    } else if (IsContentFrame(bf.video)) {
      content_count++;
    }
  }

  EXPECT_EQ(pad_count, pad_tail_frames)
      << "ALL " << pad_tail_frames << " tail frames must be pad";
  EXPECT_EQ(content_count, 0)
      << "ZERO tail frames may be repeated content (freeze frame)";
}

// =============================================================================
// INV-AIR-EOF-IMMEDIATE-001
// Pad must begin on the FIRST tick after EOF. No bridge frames.
// =============================================================================

TEST(DecodeResultModel, TEST_INV_EOF_IMMEDIATE_001_NoBridgeFrames) {
  // 100 content frames, then immediate EOF.
  std::vector<DecodeResult> script;
  for (int i = 0; i < 100; ++i) {
    script.push_back(Frame(720, 480, i));
  }
  script.push_back(Eof());

  ScriptedMockProducer producer(std::move(script));
  FillLoopSimulator sim(720, 480);

  // Content.
  for (int i = 0; i < 100; ++i) {
    sim.ProcessResult(producer.Produce());
  }

  // The VERY FIRST post-content result must be kEof.
  auto first_after = producer.Produce();
  ASSERT_EQ(first_after.status, DecodeStatus::kEof)
      << "First result after content must be kEof, not kFrame or kUnderrun";

  // And the fill loop must emit pad on that FIRST tick.
  auto bf = sim.ProcessResult(first_after);
  EXPECT_TRUE(IsPadFrame(bf.video))
      << "First fill-loop output after kEof MUST be pad — no bridge frames";
  EXPECT_FALSE(IsContentFrame(bf.video))
      << "First fill-loop output after kEof MUST NOT be held content";
}

// =============================================================================
// NEGATIVE: Pad during underrun is a violation.
// =============================================================================

TEST(DecodeResultModel, NEGATIVE_PadDuringUnderrunIsViolation) {
  // If the system emits pad during underrun, it causes visible black flashes.
  // This test verifies the fill loop does NOT produce pad on kUnderrun.

  std::vector<DecodeResult> script;
  script.push_back(Frame(720, 480, 0));
  script.push_back(Underrun());

  ScriptedMockProducer producer(std::move(script));
  FillLoopSimulator sim(720, 480);

  sim.ProcessResult(producer.Produce());  // Content frame.
  auto bf = sim.ProcessResult(producer.Produce());  // Underrun.

  // This MUST be content (held), NOT pad.
  ASSERT_FALSE(IsPadFrame(bf.video))
      << "VIOLATION: Pad frame emitted on kUnderrun — would cause black flash";
  ASSERT_TRUE(IsContentFrame(bf.video))
      << "Underrun must hold last content frame";
}

// =============================================================================
// NEGATIVE: Repeated content after EOF is a violation.
// =============================================================================

TEST(DecodeResultModel, NEGATIVE_RepeatedContentAfterEofIsViolation) {
  // If the system repeats the last content frame after EOF, the viewer
  // sees a frozen frame instead of clean black. This is the original bug.

  std::vector<DecodeResult> script;
  script.push_back(Frame(720, 480, 0));
  script.push_back(Eof());

  ScriptedMockProducer producer(std::move(script));
  FillLoopSimulator sim(720, 480);

  sim.ProcessResult(producer.Produce());  // Content.
  auto bf = sim.ProcessResult(producer.Produce());  // EOF.

  // This MUST be pad, NOT content.
  ASSERT_FALSE(IsContentFrame(bf.video))
      << "VIOLATION: Content frame repeated after kEof — freeze frame bug";
  ASSERT_TRUE(IsPadFrame(bf.video))
      << "After kEof, fill loop MUST emit pad (broadcast black)";
}

}  // namespace retrovue::blockplan::testing
