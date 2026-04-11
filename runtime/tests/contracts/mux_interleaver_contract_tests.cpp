// INV-MUX-PER-STREAM-DTS-MONOTONIC / INV-AAC-PRIMING-DROP /
// INV-MUX-CYCLE-FLUSH contract tests.
// See: docs/contracts/mux_interleaver.md
//
// These tests verify that:
// 1. Per-stream DTS is monotonically non-decreasing (audio and video independently).
// 2. Both audio and video packets are present in the output (no systematic drops).
// 3. AAC priming packets (negative DTS) are dropped cleanly — no garbage DTS=1/2.
// 4. Starting a new segment does NOT reset audio DTS to zero.
//
// All tests use EncoderPipeline WITHOUT a PacketCaptureCallback
// (PipelineManager path) and call FlushMuxInterleaver() at cycle
// boundaries (after video + audio encoding) to match production flow.

#include <climits>
#include <cstdint>
#include <unordered_map>
#include <vector>

#include <gtest/gtest.h>
#include "retrovue/playout_sinks/mpegts/EncoderPipeline.hpp"
#include "retrovue/playout_sinks/mpegts/MpegTSPlayoutSinkConfig.hpp"
#include "mpegts_sink/FrameFactory.h"

#ifdef RETROVUE_FFMPEG_AVAILABLE
extern "C" {
#include <libavformat/avformat.h>
}
#endif

namespace {

using retrovue::playout_sinks::mpegts::EncoderPipeline;
using retrovue::playout_sinks::mpegts::MpegTSPlayoutSinkConfig;
using retrovue::tests::fixtures::mpegts_sink::FrameFactory;

struct PacketWriteRecord {
  int stream_index;
  int64_t dts_90k;
  int64_t pts_90k;
};

struct CaptureState {
  std::vector<uint8_t> buffer;
  size_t total_bytes = 0;
};

static int CaptureWriteCallback(void* opaque, uint8_t* buf, int buf_size) {
  auto* s = static_cast<CaptureState*>(opaque);
  s->buffer.insert(s->buffer.end(), buf, buf + buf_size);
  s->total_bytes += buf_size;
  return buf_size;
}

MpegTSPlayoutSinkConfig CreateTestConfig() {
  MpegTSPlayoutSinkConfig config;
  config.target_width = 320;
  config.target_height = 240;
  config.target_fps = 30.0;
  config.fps_num = 30000;
  config.fps_den = 1001;
  config.bitrate = 500000;
  config.gop_size = 30;
  config.stub_mode = false;
  config.persistent_mux = true;
  config.bind_host = "";
  config.port = 0;
  return config;
}

retrovue::buffer::AudioFrame CreateSilenceAudioFrame(int64_t pts_us) {
  retrovue::buffer::AudioFrame af;
  constexpr int kAacFrameSize = 1024;
  af.sample_rate = retrovue::buffer::kHouseAudioSampleRate;
  af.channels = retrovue::buffer::kHouseAudioChannels;
  af.nb_samples = kAacFrameSize;
  af.pts_us = pts_us;
  af.data.resize(
      static_cast<size_t>(kAacFrameSize) *
      static_cast<size_t>(retrovue::buffer::kHouseAudioChannels) *
      sizeof(int16_t),
      0);
  return af;
}

// =========================================================================
// Test fixture
// =========================================================================
class MuxInterleaverContractTest : public ::testing::Test {
 protected:
  void SetUp() override { records_.clear(); }

  void AttachObserver(EncoderPipeline& pipeline) {
    pipeline.SetPacketWriteObserver(
        [this](int stream_index, int64_t dts, int64_t pts,
               int64_t dts_90k, int64_t pts_90k) {
          records_.push_back({stream_index, dts_90k, pts_90k});
        });
  }

  std::vector<PacketWriteRecord> records_;
};

#ifdef RETROVUE_FFMPEG_AVAILABLE

// =========================================================================
// TEST 1: INV-MUX-PER-STREAM-DTS-MONOTONIC — Per-stream DTS non-decreasing
// =========================================================================
// Encodes 10 cycles of video + audio. Asserts:
//   - Per-stream DTS is non-decreasing (audio and video independently)
//   - Both streams produce packets (no systematic drops)
//   - Audio packet count is reasonable (not all dropped)
// =========================================================================
TEST_F(MuxInterleaverContractTest, INV_MUX_PER_STREAM_DTS_MONOTONIC) {
  auto config = CreateTestConfig();
  CaptureState ts_capture;
  EncoderPipeline pipeline(config);

  ASSERT_TRUE(pipeline.open(config, &ts_capture, CaptureWriteCallback));
  pipeline.SetAudioLivenessEnabled(false);
  AttachObserver(pipeline);

  constexpr int kNumCycles = 10;
  constexpr int64_t kFrameDurationUs = 33367;
  constexpr int kAacFrameSize = 1024;
  constexpr int kSampleRate = 48000;
  int64_t audio_samples = 0;

  for (int i = 0; i < kNumCycles; ++i) {
    int64_t video_pts_us = i * kFrameDurationUs;
    int64_t video_pts_90k = (video_pts_us * 90000) / 1000000;

    auto frame = FrameFactory::CreateFrame(video_pts_us, 320, 240);
    pipeline.encodeFrame(frame, video_pts_90k);

    while (true) {
      int64_t audio_pts_us = (audio_samples * 1000000LL) / kSampleRate;
      if (audio_pts_us > video_pts_us) break;
      int64_t audio_pts_90k = (audio_samples * 90000) / kSampleRate;
      auto af = CreateSilenceAudioFrame(audio_pts_us);
      pipeline.encodeAudioFrame(af, audio_pts_90k, true);
      audio_samples += kAacFrameSize;
    }

    pipeline.FlushMuxInterleaver();
  }

  pipeline.close();

  ASSERT_GT(records_.size(), 0u) << "No packets written";

  // Count packets per stream and verify per-stream DTS monotonicity
  std::unordered_map<int, int64_t> last_dts_by_stream;
  int video_count = 0, audio_count = 0;

  for (size_t i = 0; i < records_.size(); ++i) {
    const auto& r = records_[i];
    if (r.stream_index == 0) ++video_count;
    if (r.stream_index == 1) ++audio_count;

    auto it = last_dts_by_stream.find(r.stream_index);
    if (it != last_dts_by_stream.end()) {
      if (r.dts_90k < it->second) {
        FAIL() << "INV-MUX-PER-STREAM-DTS-MONOTONIC VIOLATION at packet " << i
               << ": stream=" << r.stream_index
               << " dts_90k=" << r.dts_90k
               << " < last_stream_dts=" << it->second;
      }
    }
    last_dts_by_stream[r.stream_index] = r.dts_90k;
  }

  EXPECT_GT(video_count, 0) << "No video packets written";
  EXPECT_GT(audio_count, 0) << "No audio packets written";

  // Audio should not be systematically dropped — expect at least
  // half as many audio packets as video (audio cadence is ~1.5x video)
  EXPECT_GT(audio_count, video_count / 2)
      << "Too few audio packets (" << audio_count << " audio vs "
      << video_count << " video) — packets may be getting dropped";
}

// =========================================================================
// TEST 2: INV-AAC-PRIMING-DROP — No garbage DTS from priming packets
// =========================================================================
// Verifies that the first audio packet has a clean DTS (0 in 90kHz),
// not the DTS=1/2 artifact from the old clamp+bump logic.
// Also verifies both streams are present.
// =========================================================================
TEST_F(MuxInterleaverContractTest, INV_AAC_PRIMING_DROP_NoGarbageDts) {
  auto config = CreateTestConfig();
  CaptureState ts_capture;
  EncoderPipeline pipeline(config);

  ASSERT_TRUE(pipeline.open(config, &ts_capture, CaptureWriteCallback));
  pipeline.SetAudioLivenessEnabled(false);
  AttachObserver(pipeline);

  constexpr int kNumCycles = 15;
  constexpr int64_t kFrameDurationUs = 33367;
  constexpr int kAacFrameSize = 1024;
  constexpr int kSampleRate = 48000;
  int64_t audio_samples = 0;

  for (int i = 0; i < kNumCycles; ++i) {
    int64_t video_pts_us = i * kFrameDurationUs;
    int64_t video_pts_90k = (video_pts_us * 90000) / 1000000;

    auto frame = FrameFactory::CreateFrame(video_pts_us, 320, 240);
    pipeline.encodeFrame(frame, video_pts_90k);

    while (true) {
      int64_t audio_pts_us = (audio_samples * 1000000LL) / kSampleRate;
      if (audio_pts_us > video_pts_us) break;
      int64_t audio_pts_90k = (audio_samples * 90000) / kSampleRate;
      auto af = CreateSilenceAudioFrame(audio_pts_us);
      pipeline.encodeAudioFrame(af, audio_pts_90k, true);
      audio_samples += kAacFrameSize;
    }

    pipeline.FlushMuxInterleaver();
  }

  pipeline.close();

  auto& r = records_;
  ASSERT_GT(r.size(), 0u);

  bool has_video = false, has_audio = false;
  for (const auto& rec : r) {
    if (rec.stream_index == 0) has_video = true;
    if (rec.stream_index == 1) has_audio = true;
  }
  EXPECT_TRUE(has_video) << "No video packets written";
  EXPECT_TRUE(has_audio) << "No audio packets written";

  // Find first audio packet — its DTS should be 0, not 1 or 2
  for (const auto& rec : r) {
    if (rec.stream_index == 1) {
      EXPECT_EQ(rec.dts_90k, 0)
          << "INV-AAC-PRIMING-DROP: First audio DTS should be 0, got "
          << rec.dts_90k << " (priming artifact not cleaned)";
      break;
    }
  }

  // No audio packet should have DTS=1 or DTS=2 (the priming artifact)
  for (size_t i = 0; i < r.size(); ++i) {
    if (r[i].stream_index == 1) {
      EXPECT_NE(r[i].dts_90k, 1)
          << "Audio packet " << i << " has DTS=1 (priming artifact)";
      EXPECT_NE(r[i].dts_90k, 2)
          << "Audio packet " << i << " has DTS=2 (priming artifact)";
    }
  }

  // Per-stream DTS monotonicity
  std::unordered_map<int, int64_t> last_dts;
  for (size_t i = 0; i < r.size(); ++i) {
    auto it = last_dts.find(r[i].stream_index);
    if (it != last_dts.end() && r[i].dts_90k < it->second) {
      FAIL() << "Per-stream DTS regression at packet " << i
             << ": stream=" << r[i].stream_index
             << " dts_90k=" << r[i].dts_90k
             << " < prev=" << it->second;
    }
    last_dts[r[i].stream_index] = r[i].dts_90k;
  }
}

// =========================================================================
// TEST 3: INV-MUX-SESSION-CLOCK-AUTHORITY — Segment switch no DTS reset
// =========================================================================
// Simulates a segment boundary mid-session: first 5 cycles are "segment A",
// then 5 cycles are "segment B". Audio DTS must NOT reset to zero at the
// segment boundary. Per-stream DTS must remain monotonic.
// =========================================================================
TEST_F(MuxInterleaverContractTest, INV_MUX_SESSION_CLOCK_AUTHORITY_SegmentSwitchNoDtsReset) {
  auto config = CreateTestConfig();
  CaptureState ts_capture;
  EncoderPipeline pipeline(config);

  ASSERT_TRUE(pipeline.open(config, &ts_capture, CaptureWriteCallback));
  pipeline.SetAudioLivenessEnabled(false);
  AttachObserver(pipeline);

  constexpr int kCyclesPerSegment = 5;
  constexpr int kSegments = 2;
  constexpr int64_t kFrameDurationUs = 33367;
  constexpr int kAacFrameSize = 1024;
  constexpr int kSampleRate = 48000;
  int64_t audio_samples = 0;
  int cycle = 0;

  for (int seg = 0; seg < kSegments; ++seg) {
    for (int i = 0; i < kCyclesPerSegment; ++i) {
      int64_t video_pts_us = cycle * kFrameDurationUs;
      int64_t video_pts_90k = (video_pts_us * 90000) / 1000000;

      auto frame = FrameFactory::CreateFrame(video_pts_us, 320, 240);
      pipeline.encodeFrame(frame, video_pts_90k);

      while (true) {
        int64_t audio_pts_us = (audio_samples * 1000000LL) / kSampleRate;
        if (audio_pts_us > video_pts_us) break;
        int64_t audio_pts_90k = (audio_samples * 90000) / kSampleRate;
        auto af = CreateSilenceAudioFrame(audio_pts_us);
        pipeline.encodeAudioFrame(af, audio_pts_90k, true);
        audio_samples += kAacFrameSize;
      }

      pipeline.FlushMuxInterleaver();
      ++cycle;
    }
  }

  pipeline.close();

  auto& r = records_;
  ASSERT_GT(r.size(), 0u);

  // Verify per-stream DTS monotonicity — any reset would cause a regression
  std::unordered_map<int, int64_t> last_dts;
  for (size_t i = 0; i < r.size(); ++i) {
    auto it = last_dts.find(r[i].stream_index);
    if (it != last_dts.end() && r[i].dts_90k < it->second) {
      FAIL() << "INV-MUX-SESSION-CLOCK-AUTHORITY VIOLATION at packet " << i
             << ": stream=" << r[i].stream_index
             << " dts_90k=" << r[i].dts_90k
             << " < prev=" << it->second
             << " — DTS appears to have reset at segment boundary";
    }
    last_dts[r[i].stream_index] = r[i].dts_90k;
  }

  // Verify the last DTS is well past the first segment's range
  int64_t max_dts = INT64_MIN;
  for (const auto& rec : r) {
    if (rec.dts_90k > max_dts) max_dts = rec.dts_90k;
  }
  EXPECT_GT(max_dts, 20000)
      << "DTS did not advance sufficiently across segments";
}

#else  // !RETROVUE_FFMPEG_AVAILABLE

TEST(MuxInterleaverContractTest, DISABLED_RequiresFFmpeg) {
  GTEST_SKIP() << "MuxInterleaverContract tests require RETROVUE_FFMPEG_AVAILABLE";
}

#endif  // RETROVUE_FFMPEG_AVAILABLE

}  // namespace
