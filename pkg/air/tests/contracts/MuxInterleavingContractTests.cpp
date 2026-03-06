// INV-MUX-PER-STREAM-DTS-MONOTONIC / INV-MUX-INTERLEAVE-BY-DTS contract tests.
// See: docs/contracts/mux_interleaver.md
//
// These tests verify that packets written to the MPEG-TS muxer have
// per-stream non-decreasing DTS.  Cross-stream DTS differences are
// expected (audio and video have different cadences and codec delays).
//
// Architecture: Tests use EncoderPipeline with a PacketCaptureCallback
// that feeds a standalone MuxInterleaver.  The MuxInterleaver's write
// callback invokes EncoderPipeline::WriteMuxPacket(), which notifies
// the PacketWriteObserver.  This mirrors the production MpegTSOutputSink
// flow while allowing direct unit-level assertion.

#include <algorithm>
#include <climits>
#include <cstdint>
#include <cstring>
#include <functional>
#include <iostream>
#include <unordered_map>
#include <vector>

#include <gtest/gtest.h>
#include "retrovue/playout_sinks/mpegts/EncoderPipeline.hpp"
#include "retrovue/playout_sinks/mpegts/MuxInterleaver.hpp"
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
#ifdef RETROVUE_FFMPEG_AVAILABLE
using retrovue::playout_sinks::mpegts::MuxInterleaver;
#endif

// ---- Packet write record for observer-based testing ----
struct PacketWriteRecord {
  int stream_index;   // 0=video, 1=audio (typically)
  int64_t dts;        // DTS in stream time_base
  int64_t pts;        // PTS in stream time_base
  int64_t dts_90k;    // DTS rescaled to 90kHz for cross-stream comparison
  int64_t pts_90k;    // PTS rescaled to 90kHz
};

// ---- TS byte capture (AVIO callback for EncoderPipeline) ----
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

// ---- Helper: Create a standard test config ----
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

// ---- Helper: Create a silence AudioFrame in house format ----
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
// Test fixture: MuxInterleavingTest
// =========================================================================
// Sets up an EncoderPipeline + MuxInterleaver with a packet observer.
// All packets written to the muxer are captured in capture_ for assertion.
//
// This mirrors the production architecture:
//   EncoderPipeline → (capture callback) → MuxInterleaver → WriteMuxPacket
// =========================================================================
class MuxInterleavingTest : public ::testing::Test {
 protected:
  void SetUp() override {
    capture_.clear();
  }

  // Helper: set up observer on pipeline to capture packets into capture_
  void AttachObserver(EncoderPipeline& pipeline) {
    pipeline.SetPacketWriteObserver(
        [this](int stream_index, int64_t dts, int64_t pts,
               int64_t dts_90k, int64_t pts_90k) {
          capture_.push_back({stream_index, dts, pts, dts_90k, pts_90k});
        });
  }

#ifdef RETROVUE_FFMPEG_AVAILABLE
  // Helper: create a MuxInterleaver that writes via the pipeline
  std::unique_ptr<MuxInterleaver> CreateInterleaver(EncoderPipeline& pipeline) {
    return std::make_unique<MuxInterleaver>(
        [&pipeline](AVPacket* pkt, int64_t /*dts_90k*/) {
          pipeline.WriteMuxPacket(pkt);
        });
  }

  // Helper: set capture callback that routes to the interleaver
  void AttachCaptureCallback(EncoderPipeline& pipeline, MuxInterleaver& interleaver) {
    pipeline.SetPacketCaptureCallback(
        [&interleaver](AVPacket* pkt, int64_t dts_90k, int stream_index) {
          interleaver.Enqueue(pkt, dts_90k, stream_index);
        });
  }
#endif

  std::vector<PacketWriteRecord> capture_;
};

#ifdef RETROVUE_FFMPEG_AVAILABLE

// =========================================================================
// TEST: INV-MUX-PER-STREAM-DTS-MONOTONIC (external interleaver path)
// =========================================================================
// Generates a short mux run with interleaved video+audio frames and asserts
// that per-stream DTS is non-decreasing.  Cross-stream DTS differences are
// expected (audio cadence 1920 vs video cadence 3003 at 90kHz).
//
// Uses the external MuxInterleaver path (mirrors MpegTSOutputSink).
// =========================================================================
TEST_F(MuxInterleavingTest, INV_MUX_PER_STREAM_DTS_MONOTONIC_PacketHook) {
  auto config = CreateTestConfig();
  CaptureState ts_capture;
  EncoderPipeline pipeline(config);

  ASSERT_TRUE(pipeline.open(config, &ts_capture, CaptureWriteCallback))
      << "Failed to open EncoderPipeline with capture callback";

  pipeline.SetAudioLivenessEnabled(false);
  AttachObserver(pipeline);

  // Set up external interleaving (mirrors MpegTSOutputSink architecture)
  auto interleaver = CreateInterleaver(pipeline);
  interleaver->SetStartupHoldoff(true);
  AttachCaptureCallback(pipeline, *interleaver);

  // Generate 10 video frames at 29.97fps + corresponding audio frames
  // This simulates the MuxLoop pattern: encode video, then encode audio
  constexpr int kNumFrames = 10;
  constexpr int64_t kFrameDurationUs = 33367;  // ~29.97fps
  constexpr int kAacFrameSize = 1024;
  constexpr int kSampleRate = 48000;

  int64_t audio_samples_emitted = 0;

  for (int i = 0; i < kNumFrames; ++i) {
    int64_t video_pts_us = i * kFrameDurationUs;
    int64_t video_pts_90k = (video_pts_us * 90000) / 1000000;

    // Encode ONE video frame (mirrors MuxLoop Step 4)
    auto frame = FrameFactory::CreateFrame(video_pts_us, 320, 240);
    pipeline.encodeFrame(frame, video_pts_90k);

    // Encode audio frames up to video CT (mirrors MuxLoop Step 5)
    while (true) {
      int64_t audio_pts_us = (audio_samples_emitted * 1000000LL) / kSampleRate;
      if (audio_pts_us > video_pts_us) break;

      int64_t audio_pts_90k = (audio_samples_emitted * 90000) / kSampleRate;
      auto audio_frame = CreateSilenceAudioFrame(audio_pts_us);
      pipeline.encodeAudioFrame(audio_frame, audio_pts_90k, true);
      audio_samples_emitted += kAacFrameSize;
    }

    // Drain interleaving buffer in DTS order (as MuxLoop does after each tick)
    interleaver->Flush();
  }

  interleaver->DrainAll();
  pipeline.close();

  // Verify: The observer captured records
  auto& records = capture_;
  ASSERT_GT(records.size(), 0u) << "No packets were captured by the write observer";

  // Must have both video and audio packets
  bool has_video = false, has_audio = false;
  int video_count = 0, audio_count = 0;
  for (const auto& r : records) {
    if (r.stream_index == 0) { has_video = true; ++video_count; }
    if (r.stream_index == 1) { has_audio = true; ++audio_count; }
  }
  EXPECT_TRUE(has_video) << "No video packets captured";
  EXPECT_TRUE(has_audio) << "No audio packets captured";

  // =========================================================================
  // CORE ASSERTION: Per-stream DTS monotonicity
  // =========================================================================
  // Cross-stream DTS differences are expected and NOT violations.
  // Audio cadence (1920 ticks) differs from video cadence (3003 ticks).
  // See: docs/contracts/mux_interleaver.md
  // =========================================================================
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
      << video_count << " video) — packets may be getting dropped";
}

// =========================================================================
// TEST: INV-MUX-INTERLEAVE-BY-DTS (first-frame specific)
// =========================================================================
// Targets the specific failure mode: audio packets written before the
// first video packet (DTS=0) due to H.264 encoder delay.
// After interleaving, video DTS=0 must appear before any audio packet
// with DTS > 0.  Uses enough encode cycles to flush encoder delay.
// =========================================================================
TEST_F(MuxInterleavingTest, INV_MUX_INTERLEAVE_BY_DTS_FirstVideoBeforeAudio) {
  auto config = CreateTestConfig();
  CaptureState ts_capture;
  EncoderPipeline pipeline(config);

  ASSERT_TRUE(pipeline.open(config, &ts_capture, CaptureWriteCallback));
  pipeline.SetAudioLivenessEnabled(false);
  AttachObserver(pipeline);

  auto interleaver = CreateInterleaver(pipeline);
  interleaver->SetStartupHoldoff(true);
  AttachCaptureCallback(pipeline, *interleaver);

  // Encode 5 cycles to ensure encoder delay is flushed
  constexpr int kNumCycles = 5;
  constexpr int64_t kFrameDurationUs = 33367;
  constexpr int kAacFrameSize = 1024;
  constexpr int kSampleRate = 48000;
  int64_t audio_samples_emitted = 0;

  for (int i = 0; i < kNumCycles; ++i) {
    int64_t video_pts_us = i * kFrameDurationUs;
    int64_t video_pts_90k = (video_pts_us * 90000) / 1000000;

    auto frame = FrameFactory::CreateFrame(video_pts_us, 320, 240);
    pipeline.encodeFrame(frame, video_pts_90k);

    while (true) {
      int64_t audio_pts_us = (audio_samples_emitted * 1000000LL) / kSampleRate;
      if (audio_pts_us > video_pts_us) break;
      int64_t audio_pts_90k = (audio_samples_emitted * 90000) / kSampleRate;
      auto audio_frame = CreateSilenceAudioFrame(audio_pts_us);
      pipeline.encodeAudioFrame(audio_frame, audio_pts_90k, true);
      audio_samples_emitted += kAacFrameSize;
    }

    interleaver->Flush();
  }

  interleaver->DrainAll();
  pipeline.close();

  auto& records = capture_;
  ASSERT_GT(records.size(), 0u) << "No packets captured";

  // Find the first video and first audio packet
  int first_video_idx = -1;
  int first_audio_idx = -1;
  for (size_t i = 0; i < records.size(); ++i) {
    if (first_video_idx < 0 && records[i].stream_index == 0) {
      first_video_idx = static_cast<int>(i);
    }
    if (first_audio_idx < 0 && records[i].stream_index == 1) {
      first_audio_idx = static_cast<int>(i);
    }
  }

  ASSERT_GE(first_video_idx, 0) << "No video packets captured";
  ASSERT_GE(first_audio_idx, 0) << "No audio packets captured";

  // If audio DTS >= video DTS at startup, video must appear first
  // (the interleaver orders by DTS; video DTS=0 <= audio DTS=0)
  int64_t first_video_dts = records[first_video_idx].dts_90k;
  int64_t first_audio_dts = records[first_audio_idx].dts_90k;

  if (first_audio_dts >= first_video_dts) {
    EXPECT_LT(first_video_idx, first_audio_idx)
        << "INV-MUX-INTERLEAVE-BY-DTS VIOLATION: "
        << "First audio packet (dts_90k=" << first_audio_dts
        << ") was written before first video packet (dts_90k=" << first_video_dts
        << "). Audio index=" << first_audio_idx
        << ", video index=" << first_video_idx;
  }
}

// =========================================================================
// TEST: INV-MUX-PRESERVE-STREAM-ORDER
// =========================================================================
// Verifies that within each stream, the DTS order is preserved through
// the interleaving buffer. Per-stream DTS must be non-decreasing.
// =========================================================================
TEST_F(MuxInterleavingTest, INV_MUX_PRESERVE_STREAM_ORDER) {
  auto config = CreateTestConfig();
  CaptureState ts_capture;
  EncoderPipeline pipeline(config);

  ASSERT_TRUE(pipeline.open(config, &ts_capture, CaptureWriteCallback));
  pipeline.SetAudioLivenessEnabled(false);
  AttachObserver(pipeline);

  auto interleaver = CreateInterleaver(pipeline);
  interleaver->SetStartupHoldoff(true);
  AttachCaptureCallback(pipeline, *interleaver);

  constexpr int kNumFrames = 15;
  constexpr int64_t kFrameDurationUs = 33367;
  constexpr int kAacFrameSize = 1024;
  constexpr int kSampleRate = 48000;
  int64_t audio_samples_emitted = 0;

  for (int i = 0; i < kNumFrames; ++i) {
    int64_t video_pts_us = i * kFrameDurationUs;
    int64_t video_pts_90k = (video_pts_us * 90000) / 1000000;

    auto frame = FrameFactory::CreateFrame(video_pts_us, 320, 240);
    pipeline.encodeFrame(frame, video_pts_90k);

    while (true) {
      int64_t audio_pts_us = (audio_samples_emitted * 1000000LL) / kSampleRate;
      if (audio_pts_us > video_pts_us) break;
      int64_t audio_pts_90k = (audio_samples_emitted * 90000) / kSampleRate;
      auto audio_frame = CreateSilenceAudioFrame(audio_pts_us);
      pipeline.encodeAudioFrame(audio_frame, audio_pts_90k, true);
      audio_samples_emitted += kAacFrameSize;
    }

    interleaver->Flush();
  }

  interleaver->DrainAll();
  pipeline.close();

  auto& records = capture_;
  ASSERT_GT(records.size(), 0u);

  // Check per-stream DTS monotonicity
  int64_t last_video_dts = INT64_MIN;
  int64_t last_audio_dts = INT64_MIN;

  for (size_t i = 0; i < records.size(); ++i) {
    const auto& r = records[i];
    if (r.stream_index == 0) {
      EXPECT_GE(r.dts_90k, last_video_dts)
          << "INV-MUX-PRESERVE-STREAM-ORDER VIOLATION: video packet " << i
          << " has dts_90k=" << r.dts_90k << " < prev=" << last_video_dts;
      last_video_dts = r.dts_90k;
    } else if (r.stream_index == 1) {
      EXPECT_GE(r.dts_90k, last_audio_dts)
          << "INV-MUX-PRESERVE-STREAM-ORDER VIOLATION: audio packet " << i
          << " has dts_90k=" << r.dts_90k << " < prev=" << last_audio_dts;
      last_audio_dts = r.dts_90k;
    }
  }
}

// =========================================================================
// TEST: INV-MUX-BOUNDED-BUFFERING
// =========================================================================
// Verifies that DrainAll() empties the buffer completely.
// Flush() may hold back packets behind the watermark (INV-MUX-WRITE-ORDER),
// but DrainAll() must drain everything.
// =========================================================================
TEST_F(MuxInterleavingTest, INV_MUX_BOUNDED_BUFFERING_DrainAllEmptiesBuffer) {
  auto config = CreateTestConfig();
  CaptureState ts_capture;
  EncoderPipeline pipeline(config);

  ASSERT_TRUE(pipeline.open(config, &ts_capture, CaptureWriteCallback));
  pipeline.SetAudioLivenessEnabled(false);
  AttachObserver(pipeline);

  auto interleaver = CreateInterleaver(pipeline);
  AttachCaptureCallback(pipeline, *interleaver);

  // Encode video + audio
  auto frame = FrameFactory::CreateFrame(0, 320, 240);
  pipeline.encodeFrame(frame, 0);
  auto audio_frame = CreateSilenceAudioFrame(0);
  pipeline.encodeAudioFrame(audio_frame, 0, true);

  // DrainAll must empty the buffer
  interleaver->DrainAll();

  EXPECT_TRUE(interleaver->IsEmpty())
      << "INV-MUX-BOUNDED-BUFFERING VIOLATION: buffer not empty after DrainAll()";

  // A second drain should write nothing new
  size_t count_before = capture_.size();
  interleaver->DrainAll();
  size_t count_after = capture_.size();

  EXPECT_EQ(count_before, count_after)
      << "INV-MUX-BOUNDED-BUFFERING VIOLATION: DrainAll() did not "
      << "drain all packets. Second drain wrote " << (count_after - count_before)
      << " additional packets.";

  pipeline.close();
}

// =========================================================================
// TEST: INV-MUX-STARTUP-SYNC (startup holdoff)
// =========================================================================
// Simulates H.264 encoder delay: audio packets are produced for several
// iterations before the first video packet appears.  With startup holdoff
// enabled, Flush() must be a no-op until the first video packet arrives.
// Once video appears, all held packets are flushed in DTS order.
//
// Without holdoff, audio packets would be written to the muxer before any
// video packet, causing DTS ordering issues at startup.
// =========================================================================
TEST_F(MuxInterleavingTest, INV_MUX_STARTUP_HOLDOFF_VideoFirstOrTimeout) {
  auto config = CreateTestConfig();
  CaptureState ts_capture;
  EncoderPipeline pipeline(config);

  ASSERT_TRUE(pipeline.open(config, &ts_capture, CaptureWriteCallback));
  pipeline.SetAudioLivenessEnabled(false);
  AttachObserver(pipeline);

  auto interleaver = CreateInterleaver(pipeline);
  interleaver->SetStartupHoldoff(true);
  AttachCaptureCallback(pipeline, *interleaver);

  // Simulate 3 iterations of audio-only (video encoder has startup delay)
  constexpr int kAacFrameSize = 1024;
  constexpr int kSampleRate = 48000;
  int64_t audio_samples_emitted = 0;

  for (int i = 0; i < 3; ++i) {
    int64_t audio_pts_us = (audio_samples_emitted * 1000000LL) / kSampleRate;
    int64_t audio_pts_90k = (audio_samples_emitted * 90000) / kSampleRate;
    auto audio_frame = CreateSilenceAudioFrame(audio_pts_us);
    pipeline.encodeAudioFrame(audio_frame, audio_pts_90k, true);
    audio_samples_emitted += kAacFrameSize;

    // Flush should be a no-op (no video yet)
    interleaver->Flush();
  }

  // No packets should have been written yet
  EXPECT_EQ(capture_.size(), 0u)
      << "INV-MUX-STARTUP-SYNC VIOLATION: " << capture_.size()
      << " packets were written before first video packet";

  // Buffer should still hold the audio packets
  EXPECT_FALSE(interleaver->IsEmpty())
      << "INV-MUX-STARTUP-SYNC VIOLATION: buffer is empty before video arrived";

  // Now encode the first video frame (simulates H.264 encoder catching up)
  auto frame = FrameFactory::CreateFrame(0, 320, 240);
  pipeline.encodeFrame(frame, 0);

  // Flush — should now drain all held packets in DTS order
  interleaver->Flush();

  // Packets should now be written
  EXPECT_GT(capture_.size(), 0u)
      << "After first video packet, flush should have written packets";

  // Verify per-stream DTS monotonicity of the flushed packets
  std::unordered_map<int, int64_t> last_dts;
  for (size_t i = 0; i < capture_.size(); ++i) {
    const auto& r = capture_[i];
    auto it = last_dts.find(r.stream_index);
    if (it != last_dts.end() && r.dts_90k < it->second) {
      FAIL() << "INV-MUX-PER-STREAM-DTS-MONOTONIC VIOLATION at packet " << i
             << ": stream=" << r.stream_index
             << " dts_90k=" << r.dts_90k
             << " < last_stream_dts=" << it->second;
    }
    last_dts[r.stream_index] = r.dts_90k;
  }

  pipeline.close();
}

// =========================================================================
// TEST: INV-MUX-WRITE-ORDER — Global DTS ordering at mux output
// =========================================================================
// The MuxInterleaver merges video and audio into a single DTS-ordered
// output.  This test verifies that the write sequence is globally
// non-decreasing across all streams.
//
// With video cadence ~3003 and audio cadence 1920 (at 90kHz), the
// expected interleaved order is:
//   V0, A0, A1920, V3003, A3840, V6006, ...
//
// This is distinct from INV-MUX-PER-STREAM-DTS-MONOTONIC (which only
// checks within each stream).  This test proves the heap interleaver
// actually merges correctly.
// =========================================================================
TEST_F(MuxInterleavingTest, INV_MUX_WRITE_ORDER_GlobalDtsAscending) {
  auto config = CreateTestConfig();
  CaptureState ts_capture;
  EncoderPipeline pipeline(config);

  ASSERT_TRUE(pipeline.open(config, &ts_capture, CaptureWriteCallback));
  pipeline.SetAudioLivenessEnabled(false);
  AttachObserver(pipeline);

  auto interleaver = CreateInterleaver(pipeline);
  interleaver->SetStartupHoldoff(true);
  AttachCaptureCallback(pipeline, *interleaver);

  constexpr int kNumCycles = 10;
  constexpr int64_t kFrameDurationUs = 33367;  // ~29.97fps
  constexpr int kAacFrameSize = 1024;
  constexpr int kSampleRate = 48000;
  int64_t audio_samples_emitted = 0;

  for (int i = 0; i < kNumCycles; ++i) {
    int64_t video_pts_us = i * kFrameDurationUs;
    int64_t video_pts_90k = (video_pts_us * 90000) / 1000000;

    auto frame = FrameFactory::CreateFrame(video_pts_us, 320, 240);
    pipeline.encodeFrame(frame, video_pts_90k);

    while (true) {
      int64_t audio_pts_us = (audio_samples_emitted * 1000000LL) / kSampleRate;
      if (audio_pts_us > video_pts_us) break;
      int64_t audio_pts_90k = (audio_samples_emitted * 90000) / kSampleRate;
      auto audio_frame = CreateSilenceAudioFrame(audio_pts_us);
      pipeline.encodeAudioFrame(audio_frame, audio_pts_90k, true);
      audio_samples_emitted += kAacFrameSize;
    }

    interleaver->Flush();
  }

  // Drain remaining packets held back by the watermark
  interleaver->DrainAll();
  pipeline.close();

  auto& records = capture_;
  ASSERT_GT(records.size(), 0u) << "No packets captured";

  // Must have both streams
  bool has_video = false, has_audio = false;
  for (const auto& r : records) {
    if (r.stream_index == 0) has_video = true;
    if (r.stream_index == 1) has_audio = true;
  }
  ASSERT_TRUE(has_video) << "No video packets";
  ASSERT_TRUE(has_audio) << "No audio packets";

  // =========================================================================
  // CORE ASSERTION: Global DTS must be non-decreasing across all streams.
  // This proves the heap interleaver merges video (cadence 3003) and
  // audio (cadence 1920) into a single correctly-ordered output.
  // =========================================================================
  int64_t prev_dts_90k = INT64_MIN;
  for (size_t i = 0; i < records.size(); ++i) {
    const auto& r = records[i];
    if (r.dts_90k < prev_dts_90k) {
      const auto& prev = records[i - 1];
      FAIL() << "INV-MUX-WRITE-ORDER VIOLATION at packet " << i << ":\n"
             << "  Previous: stream=" << prev.stream_index
             << " dts_90k=" << prev.dts_90k << "\n"
             << "  Current:  stream=" << r.stream_index
             << " dts_90k=" << r.dts_90k << "\n"
             << "  Delta: " << (r.dts_90k - prev_dts_90k)
             << " (negative = out-of-order write)";
    }
    prev_dts_90k = r.dts_90k;
  }
}

#else  // !RETROVUE_FFMPEG_AVAILABLE

TEST(MuxInterleavingTest, DISABLED_RequiresFFmpeg) {
  GTEST_SKIP() << "MuxInterleaving tests require RETROVUE_FFMPEG_AVAILABLE";
}

#endif  // RETROVUE_FFMPEG_AVAILABLE

}  // namespace
