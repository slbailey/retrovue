// INV-MUX-STARTUP-HOLDOFF contract tests.
// See: docs/contracts/mux_startup_interleave_contract.md
//
// These tests verify that the muxer does NOT write any packet until at least
// one packet from EVERY active stream (audio and video) has been observed
// in the interleave buffer.
//
// Tests use MuxInterleaver directly (no EncoderPipeline) to isolate the
// holdoff logic from encoding concerns.

#include <climits>
#include <cstdint>
#include <memory>
#include <vector>

#include <gtest/gtest.h>
#include "retrovue/playout_sinks/mpegts/MuxInterleaver.hpp"

#ifdef RETROVUE_FFMPEG_AVAILABLE
extern "C" {
#include <libavcodec/avcodec.h>
}
#endif

namespace {

#ifdef RETROVUE_FFMPEG_AVAILABLE

using retrovue::playout_sinks::mpegts::MuxInterleaver;

struct FlushedPacket {
  int64_t dts_90k;
  int stream_index;
};

// Create a minimal AVPacket for testing (no real encoded data needed).
AVPacket* MakeTestPacket(int stream_index, int64_t dts) {
  AVPacket* pkt = av_packet_alloc();
  pkt->stream_index = stream_index;
  pkt->dts = dts;
  pkt->pts = dts;
  return pkt;
}

class MuxStartupInterleaveTest : public ::testing::Test {
 protected:
  void SetUp() override { flushed_.clear(); }

  std::unique_ptr<MuxInterleaver> CreateInterleaver() {
    return std::make_unique<MuxInterleaver>(
        [this](AVPacket* pkt, int64_t dts_90k) {
          flushed_.push_back({dts_90k, pkt->stream_index});
        });
  }

  std::vector<FlushedPacket> flushed_;
};

// =========================================================================
// TEST 1: INV_MUX_STARTUP_HOLDOFF_AudioFirst
// =========================================================================
// Audio packets arrive before video (AAC has no lookahead, H.264 does).
// With startup holdoff enabled, Flush() MUST be a no-op until BOTH
// audio AND video packets have been enqueued.
// =========================================================================
TEST_F(MuxStartupInterleaveTest, INV_MUX_STARTUP_HOLDOFF_AudioFirst) {
  auto interleaver = CreateInterleaver();
  interleaver->SetStartupHoldoff(true);

  // Audio packets arrive first (AAC encoder produces output immediately)
  interleaver->Enqueue(MakeTestPacket(1, 0), /*dts_90k=*/0, /*stream_index=*/1);
  interleaver->Flush();
  EXPECT_EQ(flushed_.size(), 0u)
      << "VIOLATION: Packets written with only audio (no video yet)";

  interleaver->Enqueue(MakeTestPacket(1, 1920), /*dts_90k=*/1920, /*stream_index=*/1);
  interleaver->Flush();
  EXPECT_EQ(flushed_.size(), 0u)
      << "VIOLATION: Packets written with only audio (no video yet)";

  interleaver->Enqueue(MakeTestPacket(1, 3840), /*dts_90k=*/3840, /*stream_index=*/1);
  interleaver->Flush();
  EXPECT_EQ(flushed_.size(), 0u)
      << "VIOLATION: Packets written with only audio (no video yet)";

  // First video packet arrives (H.264 encoder catches up)
  interleaver->Enqueue(MakeTestPacket(0, 0), /*dts_90k=*/0, /*stream_index=*/0);
  interleaver->Flush();

  // NOW packets should start flowing
  EXPECT_GT(flushed_.size(), 0u)
      << "After both streams seen, Flush must drain held packets";

  // DrainAll must empty the buffer completely
  interleaver->DrainAll();
  EXPECT_TRUE(interleaver->IsEmpty());
}

// =========================================================================
// TEST 2: INV_MUX_STARTUP_HOLDOFF_FirstVideoPrecedesFutureAudio
// =========================================================================
// After holdoff releases, the first written packet must have the lowest
// DTS. Since video DTS=0 ties with audio DTS=0, and the min-heap breaks
// ties by stream_index (video=0 before audio=1), video MUST be first.
// =========================================================================
TEST_F(MuxStartupInterleaveTest, INV_MUX_STARTUP_HOLDOFF_FirstVideoPrecedesFutureAudio) {
  auto interleaver = CreateInterleaver();
  interleaver->SetStartupHoldoff(true);

  // Audio: DTS 0, 1920, 3840 (3 frames before video)
  interleaver->Enqueue(MakeTestPacket(1, 0), 0, 1);
  interleaver->Enqueue(MakeTestPacket(1, 1920), 1920, 1);
  interleaver->Enqueue(MakeTestPacket(1, 3840), 3840, 1);

  // Video: DTS 0 (first keyframe from H.264)
  interleaver->Enqueue(MakeTestPacket(0, 0), 0, 0);

  interleaver->Flush();

  ASSERT_GT(flushed_.size(), 0u);

  // First packet written must be video (stream_index=0) because on DTS tie,
  // video (0) sorts before audio (1) in the min-heap comparator.
  EXPECT_EQ(flushed_[0].stream_index, 0)
      << "INV-MUX-STARTUP-HOLDOFF VIOLATION: first written packet is audio "
      << "(stream=" << flushed_[0].stream_index
      << " dts=" << flushed_[0].dts_90k
      << "), expected video (stream=0)";
}

// =========================================================================
// TEST 3: INV_MUX_GLOBAL_DTS_MONOTONIC (post-holdoff)
// =========================================================================
// After the startup holdoff releases, ALL flushed packets must have
// globally non-decreasing DTS. This is the foundational mux invariant
// that the holdoff exists to protect.
// =========================================================================
TEST_F(MuxStartupInterleaveTest, INV_MUX_GLOBAL_DTS_MONOTONIC_AfterHoldoff) {
  auto interleaver = CreateInterleaver();
  interleaver->SetStartupHoldoff(true);

  // Simulate encoder startup: 5 audio frames before first video
  for (int i = 0; i < 5; ++i) {
    int64_t dts = i * 1920;  // AAC frame duration at 90kHz
    interleaver->Enqueue(MakeTestPacket(1, dts), dts, 1);
    interleaver->Flush();  // All should be no-ops
  }
  EXPECT_EQ(flushed_.size(), 0u);

  // Video arrives: 3 frames
  for (int i = 0; i < 3; ++i) {
    int64_t dts = i * 3003;  // 29.97fps at 90kHz
    interleaver->Enqueue(MakeTestPacket(0, dts), dts, 0);
  }

  // More audio to interleave with video
  for (int i = 5; i < 10; ++i) {
    int64_t dts = i * 1920;
    interleaver->Enqueue(MakeTestPacket(1, dts), dts, 1);
  }

  interleaver->DrainAll();

  ASSERT_GT(flushed_.size(), 0u);

  // Core assertion: global DTS monotonicity
  int64_t prev_dts = INT64_MIN;
  for (size_t i = 0; i < flushed_.size(); ++i) {
    EXPECT_GE(flushed_[i].dts_90k, prev_dts)
        << "INV-MUX-GLOBAL-DTS-MONOTONIC VIOLATION at packet " << i
        << ": dts_90k=" << flushed_[i].dts_90k
        << " < prev=" << prev_dts
        << " stream=" << flushed_[i].stream_index;
    prev_dts = flushed_[i].dts_90k;
  }
}

// =========================================================================
// TEST 4: INV_MUX_STARTUP_HOLDOFF_VideoOnly
// =========================================================================
// Video arrives before audio. Holdoff must NOT release until audio also
// arrives. This test catches the specific bug where the holdoff only
// checks first_video_seen_ but not first_audio_seen_.
// =========================================================================
TEST_F(MuxStartupInterleaveTest, INV_MUX_STARTUP_HOLDOFF_VideoOnly) {
  auto interleaver = CreateInterleaver();
  interleaver->SetStartupHoldoff(true);

  // Video packet arrives first
  interleaver->Enqueue(MakeTestPacket(0, 0), /*dts_90k=*/0, /*stream_index=*/0);
  interleaver->Flush();

  // Holdoff must NOT release: audio hasn't been seen yet
  EXPECT_EQ(flushed_.size(), 0u)
      << "INV-MUX-STARTUP-HOLDOFF VIOLATION: Packets written with only video "
      << "(no audio yet). Both streams must be observed before any flush.";

  // Audio arrives
  interleaver->Enqueue(MakeTestPacket(1, 0), /*dts_90k=*/0, /*stream_index=*/1);
  interleaver->Flush();

  // Now packets should drain
  EXPECT_GT(flushed_.size(), 0u)
      << "After both streams seen, Flush must drain held packets";
}

#else  // !RETROVUE_FFMPEG_AVAILABLE

TEST(MuxStartupInterleaveTest, DISABLED_RequiresFFmpeg) {
  GTEST_SKIP() << "MuxStartupInterleave tests require RETROVUE_FFMPEG_AVAILABLE";
}

#endif  // RETROVUE_FFMPEG_AVAILABLE

}  // namespace
