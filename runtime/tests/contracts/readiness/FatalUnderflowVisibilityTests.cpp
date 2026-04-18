// Contract tests for INV-FATAL-UNDERFLOW-VISIBILITY-001.
//
// Cross-reference:
//   docs/contracts/invariants/air/INV-FATAL-UNDERFLOW-VISIBILITY-001.md
//
// RED contract-test status:
//   The production surface this invariant requires does not yet exist. AIR
//   currently detects underflow only via counter increments on the lookahead
//   buffers (VideoLookaheadBuffer::UnderflowCount, AudioLookaheadBuffer::
//   UnderflowCount); it does not emit a structured error with the required
//   fields, nor does it increment a session-fatal metric counter at the
//   termination site.
//
//   These tests encode the canonical contract. They remain RED until a
//   dedicated emission site is implemented. ReadinessController Phase 1
//   (Turn C) does NOT land that emission — it consumes counter edges as a
//   substitute input to its verdict. A future implementation turn is
//   expected to close the code gap named in INVARIANTS.md §Governance Pass
//   Notes for INV-FATAL-UNDERFLOW-VISIBILITY-001.
//
//   This file is intentionally shipped RED as a tripwire for that future
//   work.

#include <gtest/gtest.h>

#include <cstdint>
#include <string>
#include <vector>

// Turn C / future underflow-emission work will create this header. Missing
// header compile failure is the RED contract-test signal.
#include "retrovue/readiness/FatalUnderflowEmitter.h"

namespace retrovue::readiness::test {

namespace {

// Capture target injected into FatalUnderflowEmitter for test inspection.
// The production emitter will also wire into MetricsExporter and the
// structured logger; the capture surface is the contract-test seam.
struct FatalUnderflowCapture {
  struct Record {
    std::string reason;
    int64_t tick = 0;
    std::string block_id;
    bool decoder_ok = false;
    int video_depth = 0;
    int audio_depth_ms = 0;
  };
  std::vector<Record> records;
  std::uint64_t session_fatal_counter = 0;

  void OnFatalUnderflow(const Record& r) {
    records.push_back(r);
    ++session_fatal_counter;
  }
};

}  // namespace

// ===========================================================================
// INV-FATAL-UNDERFLOW-VISIBILITY-001 — Boundary/Constraint: required fields
// ===========================================================================

TEST(FatalUnderflowVisibility, StructuredRecordCarriesAllRequiredFields) {
  FatalUnderflowCapture capture;
  auto emitter = FatalUnderflowEmitter::CreateForTest(
      [&capture](const FatalUnderflowEmitter::Record& r) {
        FatalUnderflowCapture::Record copy{};
        copy.reason = r.reason;
        copy.tick = r.tick;
        copy.block_id = r.block_id;
        copy.decoder_ok = r.decoder_ok;
        copy.video_depth = r.video_depth;
        copy.audio_depth_ms = r.audio_depth_ms;
        capture.OnFatalUnderflow(copy);
      });

  emitter->EmitFatalUnderflow(/*reason=*/"post_primed_video_underflow",
                              /*tick=*/12345,
                              /*block_id=*/"block-abc",
                              /*decoder_ok=*/false,
                              /*video_depth=*/0,
                              /*audio_depth_ms=*/150);

  ASSERT_EQ(capture.records.size(), 1u);
  const auto& rec = capture.records.front();
  EXPECT_EQ(rec.reason, "post_primed_video_underflow");
  EXPECT_EQ(rec.tick, 12345);
  EXPECT_EQ(rec.block_id, "block-abc");
  EXPECT_EQ(rec.decoder_ok, false);
  EXPECT_EQ(rec.video_depth, 0);
  EXPECT_EQ(rec.audio_depth_ms, 150);
}

// ===========================================================================
// INV-FATAL-UNDERFLOW-VISIBILITY-001 — counter increment exactly once per event
// ===========================================================================

TEST(FatalUnderflowVisibility, SessionFatalCounterIncrementsOncePerEvent) {
  FatalUnderflowCapture capture;
  auto emitter = FatalUnderflowEmitter::CreateForTest(
      [&capture](const FatalUnderflowEmitter::Record& r) {
        FatalUnderflowCapture::Record copy{};
        copy.reason = r.reason;
        copy.tick = r.tick;
        copy.block_id = r.block_id;
        copy.decoder_ok = r.decoder_ok;
        copy.video_depth = r.video_depth;
        copy.audio_depth_ms = r.audio_depth_ms;
        capture.OnFatalUnderflow(copy);
      });

  emitter->EmitFatalUnderflow("u1", 1, "b1", false, 0, 0);
  EXPECT_EQ(capture.session_fatal_counter, 1u);

  emitter->EmitFatalUnderflow("u2", 2, "b2", false, 0, 0);
  EXPECT_EQ(capture.session_fatal_counter, 2u);
}

// ===========================================================================
// INV-FATAL-UNDERFLOW-VISIBILITY-001 — scope: pre-primed underflow excluded
// ===========================================================================

TEST(FatalUnderflowVisibility, PrePrimedUnderflowDoesNotIncrementSessionFatalCounter) {
  // The invariant excludes pre-primed underflow. NotePrePrimedUnderflow is
  // the non-terminating counter path; it MUST NOT increment the session-
  // fatal counter nor emit a structured record.
  FatalUnderflowCapture capture;
  auto emitter = FatalUnderflowEmitter::CreateForTest(
      [&capture](const FatalUnderflowEmitter::Record& r) {
        FatalUnderflowCapture::Record copy{};
        copy.reason = r.reason;
        copy.tick = r.tick;
        copy.block_id = r.block_id;
        copy.decoder_ok = r.decoder_ok;
        copy.video_depth = r.video_depth;
        copy.audio_depth_ms = r.audio_depth_ms;
        capture.OnFatalUnderflow(copy);
      });

  emitter->NotePrePrimedUnderflow();

  EXPECT_EQ(capture.session_fatal_counter, 0u);
  EXPECT_EQ(capture.records.size(), 0u);
}

}  // namespace retrovue::readiness::test
