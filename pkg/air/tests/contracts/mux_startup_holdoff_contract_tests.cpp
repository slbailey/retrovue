// INV-MUX-STARTUP-HOLDOFF contract tests.
// See: docs/contracts/mux_startup_holdoff_contract.md
//
// These tests verify that the muxer does NOT write any packet to
// av_write_frame() until at least one packet from EVERY active stream
// (audio and video) has been observed.
//
// Critical: These tests use EncoderPipeline WITHOUT a PacketCaptureCallback,
// which is the PipelineManager (BlockPlan) production path.  This is the
// code path where the startup DTS regression was observed.

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
  int64_t dts;
  int64_t pts;
  int64_t dts_90k;
  int64_t pts_90k;
};

// TS byte capture (AVIO callback for EncoderPipeline)
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
// Test fixture: MuxStartupHoldoffTest
// =========================================================================
// Sets up an EncoderPipeline WITHOUT a PacketCaptureCallback.
// This exercises the same code path as PipelineManager (BlockPlan mode),
// where the startup DTS regression was observed in production.
//
// The PacketWriteObserver captures every packet written to av_write_frame().
// =========================================================================
class MuxStartupHoldoffTest : public ::testing::Test {
 protected:
  void SetUp() override {
    capture_.clear();
  }

  void AttachObserver(EncoderPipeline& pipeline) {
    pipeline.SetPacketWriteObserver(
        [this](int stream_index, int64_t dts, int64_t pts,
               int64_t dts_90k, int64_t pts_90k) {
          capture_.push_back({stream_index, dts, pts, dts_90k, pts_90k});
        });
  }

  std::vector<PacketWriteRecord> capture_;
};

#ifdef RETROVUE_FFMPEG_AVAILABLE

// =========================================================================
// TEST: AudioFirst_NoWritesUntilVideoSeen
// =========================================================================
// Simulates AAC producing packets before H.264 (encoder startup delay).
// Audio frames are encoded for 3 iterations with NO video frames.
// Assert: PacketWriteObserver receives 0 packets until video is observed.
// After video is observed, flushing begins.
//
// This test exercises the NO-capture-callback path (PipelineManager path).
// =========================================================================
TEST_F(MuxStartupHoldoffTest, AudioFirst_NoWritesUntilVideoSeen) {
  auto config = CreateTestConfig();
  CaptureState ts_capture;
  EncoderPipeline pipeline(config);

  ASSERT_TRUE(pipeline.open(config, &ts_capture, CaptureWriteCallback))
      << "Failed to open EncoderPipeline";

  pipeline.SetAudioLivenessEnabled(false);
  // NO PacketCaptureCallback set — this is the PipelineManager path
  AttachObserver(pipeline);

  // Encode 3 audio frames WITHOUT any video (simulates H.264 startup delay)
  constexpr int kAacFrameSize = 1024;
  constexpr int kSampleRate = 48000;
  int64_t audio_samples = 0;

  for (int i = 0; i < 3; ++i) {
    int64_t audio_pts_90k = (audio_samples * 90000) / kSampleRate;
    int64_t audio_pts_us = (audio_samples * 1000000LL) / kSampleRate;
    auto af = CreateSilenceAudioFrame(audio_pts_us);
    pipeline.encodeAudioFrame(af, audio_pts_90k, true);
    audio_samples += kAacFrameSize;
  }

  // INV-MUX-STARTUP-HOLDOFF: No packets should have been written yet
  // (no video has been produced)
  EXPECT_EQ(capture_.size(), 0u)
      << "INV-MUX-STARTUP-HOLDOFF VIOLATION: " << capture_.size()
      << " packets written before first video packet was produced.\n"
      << "First written: stream=" << (capture_.empty() ? -1 : capture_[0].stream_index)
      << " dts_90k=" << (capture_.empty() ? -1 : capture_[0].dts_90k);

  // Now encode first video frame (H.264 encoder catches up)
  auto frame = FrameFactory::CreateFrame(0, 320, 240);
  pipeline.encodeFrame(frame, 0);

  // Encode a second video frame to flush H.264 encoder delay
  auto frame2 = FrameFactory::CreateFrame(33367, 320, 240);
  pipeline.encodeFrame(frame2, 3003);

  // More audio to accompany
  for (int i = 0; i < 2; ++i) {
    int64_t audio_pts_90k = (audio_samples * 90000) / kSampleRate;
    int64_t audio_pts_us = (audio_samples * 1000000LL) / kSampleRate;
    auto af = CreateSilenceAudioFrame(audio_pts_us);
    pipeline.encodeAudioFrame(af, audio_pts_90k, true);
    audio_samples += kAacFrameSize;
  }

  // INV-MUX-CYCLE-FLUSH: Flush at cycle boundary (after video+audio)
  pipeline.FlushMuxInterleaver();

  // After video is present and cycle flushed, packets should now be flowing
  EXPECT_GT(capture_.size(), 0u)
      << "After first video packet, mux writes should have begun";

  pipeline.close();
}

// =========================================================================
// TEST: FirstVideoDts0_NotWrittenAfterAudioDtsPositive
// =========================================================================
// Reproduces the exact observed failure trace:
//   A(dts=1), A(dts=2), A(dts=1920), A(dts=3840), V(dts=0)
//
// The first video packet (DTS=0) must be the FIRST packet written to the
// muxer, not written after audio packets with DTS>0.
//
// This test exercises the NO-capture-callback path (PipelineManager path).
// =========================================================================
TEST_F(MuxStartupHoldoffTest, FirstVideoDts0_NotWrittenAfterAudioDtsPositive) {
  auto config = CreateTestConfig();
  CaptureState ts_capture;
  EncoderPipeline pipeline(config);

  ASSERT_TRUE(pipeline.open(config, &ts_capture, CaptureWriteCallback));
  pipeline.SetAudioLivenessEnabled(false);
  // NO PacketCaptureCallback — PipelineManager path
  AttachObserver(pipeline);

  // Encode 4 audio frames (matching observed failure: DTS 0, 1920, 3840, 5760)
  constexpr int kAacFrameSize = 1024;
  constexpr int kSampleRate = 48000;
  int64_t audio_samples = 0;

  for (int i = 0; i < 4; ++i) {
    int64_t audio_pts_90k = (audio_samples * 90000) / kSampleRate;
    int64_t audio_pts_us = (audio_samples * 1000000LL) / kSampleRate;
    auto af = CreateSilenceAudioFrame(audio_pts_us);
    pipeline.encodeAudioFrame(af, audio_pts_90k, true);
    audio_samples += kAacFrameSize;
  }

  // No packets written yet (holdoff)
  EXPECT_EQ(capture_.size(), 0u)
      << "INV-MUX-STARTUP-HOLDOFF: audio packets written before video";

  // First video frame (DTS=0)
  auto frame0 = FrameFactory::CreateFrame(0, 320, 240);
  pipeline.encodeFrame(frame0, 0);

  // Second video frame to flush encoder delay
  auto frame1 = FrameFactory::CreateFrame(33367, 320, 240);
  pipeline.encodeFrame(frame1, 3003);

  // Third video frame (may be needed for B-frame encoder to produce output)
  auto frame2 = FrameFactory::CreateFrame(66734, 320, 240);
  pipeline.encodeFrame(frame2, 6006);

  pipeline.close();

  // Must have written packets
  ASSERT_GT(capture_.size(), 0u) << "No packets captured at all";

  // Find first video and first audio in the write sequence
  int first_video_idx = -1;
  int first_audio_idx = -1;
  for (size_t i = 0; i < capture_.size(); ++i) {
    if (first_video_idx < 0 && capture_[i].stream_index == 0)
      first_video_idx = static_cast<int>(i);
    if (first_audio_idx < 0 && capture_[i].stream_index == 1)
      first_audio_idx = static_cast<int>(i);
  }

  ASSERT_GE(first_video_idx, 0) << "No video packets written";
  ASSERT_GE(first_audio_idx, 0) << "No audio packets written";

  // INV-MUX-STARTUP-FIRST-PACKET: Video DTS=0 must appear before any
  // audio packet with DTS>0. Since video DTS <= audio DTS at startup,
  // video must be written first.
  int64_t first_video_dts = capture_[first_video_idx].dts_90k;
  int64_t first_audio_dts = capture_[first_audio_idx].dts_90k;

  // The first video DTS should be <= first audio DTS after interleaving
  if (first_audio_dts >= first_video_dts) {
    EXPECT_LT(first_video_idx, first_audio_idx)
        << "INV-MUX-STARTUP-FIRST-PACKET VIOLATION:\n"
        << "  First video packet: index=" << first_video_idx
        << " dts_90k=" << first_video_dts << "\n"
        << "  First audio packet: index=" << first_audio_idx
        << " dts_90k=" << first_audio_dts << "\n"
        << "  Video should be written before audio when video DTS <= audio DTS";
  }
}

// =========================================================================
// TEST: PerStreamDtsMonotonic_AcrossStreams
// =========================================================================
// After both streams are observed, feed a mix of video+audio frames and
// assert that per-stream DTS is non-decreasing.  Cross-stream DTS
// differences are expected (audio cadence 1920 vs video cadence 3003).
//
// This test exercises the NO-capture-callback path (PipelineManager path).
// =========================================================================
TEST_F(MuxStartupHoldoffTest, PerStreamDtsMonotonic_AcrossStreams) {
  auto config = CreateTestConfig();
  CaptureState ts_capture;
  EncoderPipeline pipeline(config);

  ASSERT_TRUE(pipeline.open(config, &ts_capture, CaptureWriteCallback));
  pipeline.SetAudioLivenessEnabled(false);
  // NO PacketCaptureCallback — PipelineManager path
  AttachObserver(pipeline);

  // Encode 10 video frames at 29.97fps with interleaved audio
  constexpr int kNumFrames = 10;
  constexpr int64_t kFrameDurationUs = 33367;  // ~29.97fps
  constexpr int kAacFrameSize = 1024;
  constexpr int kSampleRate = 48000;
  int64_t audio_samples = 0;

  for (int i = 0; i < kNumFrames; ++i) {
    int64_t video_pts_us = i * kFrameDurationUs;
    int64_t video_pts_90k = (video_pts_us * 90000) / 1000000;

    // Encode video frame
    auto frame = FrameFactory::CreateFrame(video_pts_us, 320, 240);
    pipeline.encodeFrame(frame, video_pts_90k);

    // Encode audio frames up to video CT
    while (true) {
      int64_t audio_pts_us = (audio_samples * 1000000LL) / kSampleRate;
      if (audio_pts_us > video_pts_us) break;
      int64_t audio_pts_90k = (audio_samples * 90000) / kSampleRate;
      auto af = CreateSilenceAudioFrame(audio_pts_us);
      pipeline.encodeAudioFrame(af, audio_pts_90k, true);
      audio_samples += kAacFrameSize;
    }

    // INV-MUX-CYCLE-FLUSH: Flush at cycle boundary
    pipeline.FlushMuxInterleaver();
  }

  pipeline.close();

  auto& records = capture_;
  ASSERT_GT(records.size(), 0u) << "No packets captured";

  // Must have both streams
  bool has_video = false, has_audio = false;
  int video_count = 0, audio_count = 0;
  for (const auto& r : records) {
    if (r.stream_index == 0) { has_video = true; ++video_count; }
    if (r.stream_index == 1) { has_audio = true; ++audio_count; }
  }
  EXPECT_TRUE(has_video) << "No video packets";
  EXPECT_TRUE(has_audio) << "No audio packets";

  // INV-MUX-PER-STREAM-DTS-MONOTONIC: Per-stream DTS must be non-decreasing
  std::unordered_map<int, int64_t> last_dts_by_stream;
  for (size_t i = 0; i < records.size(); ++i) {
    const auto& r = records[i];
    auto it = last_dts_by_stream.find(r.stream_index);
    if (it != last_dts_by_stream.end() && r.dts_90k < it->second) {
      FAIL() << "INV-MUX-PER-STREAM-DTS-MONOTONIC VIOLATION at packet " << i
             << ": stream=" << r.stream_index
             << " dts_90k=" << r.dts_90k
             << " < last_stream_dts=" << it->second;
    }
    last_dts_by_stream[r.stream_index] = r.dts_90k;
  }

  // Audio should not be systematically dropped
  EXPECT_GT(audio_count, video_count / 2)
      << "Too few audio packets (" << audio_count << " audio vs "
      << video_count << " video)";
}

#else  // !RETROVUE_FFMPEG_AVAILABLE

TEST(MuxStartupHoldoffTest, DISABLED_RequiresFFmpeg) {
  GTEST_SKIP() << "MuxStartupHoldoff tests require RETROVUE_FFMPEG_AVAILABLE";
}

#endif  // RETROVUE_FFMPEG_AVAILABLE

}  // namespace
