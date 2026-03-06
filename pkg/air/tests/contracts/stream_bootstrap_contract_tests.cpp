// INV-STREAM-JOINABLE / INV-H264-PARAMETER-SETS / INV-STREAM-BOOTSTRAP-BOUND
// contract tests.
// See: docs/contracts/stream_bootstrap.md
//
// These tests verify the OBSERVABLE TS output that a viewer would receive.
// They encode video, capture the muxed MPEG-TS bytes, then demux and
// inspect the H.264 NAL units in the video packets.
//
// This tests the end-to-end path: encoder → muxer → transport bytes →
// demuxer → NAL inspection.  If SPS/PPS is stripped or misordered by
// the muxer, these tests will catch it.

#include <cstdint>
#include <cstring>
#include <iostream>
#include <vector>

#include <gtest/gtest.h>
#include "retrovue/playout_sinks/mpegts/EncoderPipeline.hpp"
#include "retrovue/playout_sinks/mpegts/MpegTSPlayoutSinkConfig.hpp"
#include "mpegts_sink/FrameFactory.h"

#ifdef RETROVUE_FFMPEG_AVAILABLE
extern "C" {
#include <libavcodec/avcodec.h>
#include <libavformat/avformat.h>
#include <libavformat/avio.h>
}
#endif

namespace {

using retrovue::playout_sinks::mpegts::EncoderPipeline;
using retrovue::playout_sinks::mpegts::MpegTSPlayoutSinkConfig;
using retrovue::tests::fixtures::mpegts_sink::FrameFactory;

// H.264 NAL unit types (ITU-T H.264 Table 7-1)
constexpr uint8_t kNalTypeSlice    = 1;   // Non-IDR slice
constexpr uint8_t kNalTypeIDR      = 5;   // IDR slice
constexpr uint8_t kNalTypeSPS      = 7;   // Sequence Parameter Set
constexpr uint8_t kNalTypePPS      = 8;   // Picture Parameter Set

struct NalUnit {
  uint8_t type;
  size_t offset;
  size_t size;
};

// Parse H.264 Annex B NAL units from raw packet data.
std::vector<NalUnit> ParseNalUnits(const uint8_t* data, size_t size) {
  std::vector<NalUnit> nals;
  if (!data || size < 4) return nals;

  std::vector<size_t> starts;
  for (size_t i = 0; i + 2 < size; ++i) {
    if (data[i] == 0 && data[i + 1] == 0) {
      if (data[i + 2] == 1) {
        starts.push_back(i + 3);
        i += 2;
      } else if (i + 3 < size && data[i + 2] == 0 && data[i + 3] == 1) {
        starts.push_back(i + 4);
        i += 3;
      }
    }
  }

  for (size_t i = 0; i < starts.size(); ++i) {
    size_t nal_start = starts[i];
    if (nal_start >= size) continue;
    size_t nal_end = (i + 1 < starts.size()) ? starts[i + 1] : size;
    if (i + 1 < starts.size()) {
      while (nal_end > nal_start && data[nal_end - 1] == 0) --nal_end;
    }
    uint8_t nal_type = data[nal_start] & 0x1F;
    nals.push_back({nal_type, nal_start, nal_end - nal_start});
  }

  return nals;
}

// Record of a demuxed video packet and its NAL composition.
struct VideoPacketRecord {
  int64_t dts;
  int64_t pts;
  std::vector<NalUnit> nal_units;
  bool has_sps{false};
  bool has_pps{false};
  bool has_idr{false};
  bool has_non_idr{false};
  bool is_keyframe{false};
};

// TS byte capture (AVIO write callback for EncoderPipeline)
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

// AVIO read callback for demuxing captured TS bytes
struct ReadState {
  const uint8_t* data;
  size_t size;
  size_t pos;
};

static int ReadCallback(void* opaque, uint8_t* buf, int buf_size) {
  auto* s = static_cast<ReadState*>(opaque);
  size_t remaining = s->size - s->pos;
  if (remaining == 0) return AVERROR_EOF;
  size_t to_read = std::min(static_cast<size_t>(buf_size), remaining);
  memcpy(buf, s->data + s->pos, to_read);
  s->pos += to_read;
  return static_cast<int>(to_read);
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

#ifdef RETROVUE_FFMPEG_AVAILABLE

// Encode video+audio, capture TS bytes, then demux and extract video packets.
// Returns the demuxed video packet records with NAL analysis.
// This tests the full encoder→muxer→transport→demuxer path.
std::vector<VideoPacketRecord> EncodeAndDemux(
    MpegTSPlayoutSinkConfig& config, int num_frames) {

  // Phase 1: Encode and capture TS bytes
  CaptureState ts_capture;
  EncoderPipeline pipeline(config);

  if (!pipeline.open(config, &ts_capture, CaptureWriteCallback)) {
    return {};
  }
  pipeline.SetAudioLivenessEnabled(false);

  constexpr int64_t kFrameDurationUs = 33367;
  constexpr int kAacFrameSize = 1024;
  constexpr int kSampleRate = 48000;
  int64_t audio_samples = 0;

  for (int i = 0; i < num_frames; ++i) {
    int64_t video_pts_us = i * kFrameDurationUs;
    int64_t video_pts_90k = (video_pts_us * 90000) / 1000000;

    auto frame = FrameFactory::CreateFrame(video_pts_us, 320, 240);
    pipeline.encodeFrame(frame, video_pts_90k);

    // Encode audio to keep mux happy
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

  if (ts_capture.buffer.empty()) return {};

  // Phase 2: Demux the captured TS bytes
  ReadState read_state{ts_capture.buffer.data(), ts_capture.buffer.size(), 0};

  constexpr size_t kAvioBufferSize = 4096;
  uint8_t* avio_buffer = static_cast<uint8_t*>(av_malloc(kAvioBufferSize));
  AVIOContext* avio_ctx = avio_alloc_context(
      avio_buffer, kAvioBufferSize, 0, &read_state, ReadCallback, nullptr, nullptr);
  if (!avio_ctx) {
    av_free(avio_buffer);
    return {};
  }

  AVFormatContext* fmt_ctx = avformat_alloc_context();
  fmt_ctx->pb = avio_ctx;
  fmt_ctx->flags |= AVFMT_FLAG_CUSTOM_IO;

  const AVInputFormat* input_fmt = av_find_input_format("mpegts");
  if (avformat_open_input(&fmt_ctx, nullptr, input_fmt, nullptr) < 0) {
    avio_context_free(&avio_ctx);
    return {};
  }

  avformat_find_stream_info(fmt_ctx, nullptr);

  // Find the video stream
  int video_stream_idx = -1;
  for (unsigned i = 0; i < fmt_ctx->nb_streams; ++i) {
    if (fmt_ctx->streams[i]->codecpar->codec_id == AV_CODEC_ID_H264) {
      video_stream_idx = static_cast<int>(i);
      break;
    }
  }

  std::vector<VideoPacketRecord> records;

  if (video_stream_idx >= 0) {
    AVPacket* pkt = av_packet_alloc();
    while (av_read_frame(fmt_ctx, pkt) >= 0) {
      if (pkt->stream_index == video_stream_idx && pkt->data && pkt->size > 0) {
        VideoPacketRecord rec;
        rec.dts = pkt->dts;
        rec.pts = pkt->pts;
        rec.is_keyframe = (pkt->flags & AV_PKT_FLAG_KEY) != 0;
        rec.nal_units = ParseNalUnits(pkt->data, pkt->size);

        for (const auto& nal : rec.nal_units) {
          if (nal.type == kNalTypeSPS) rec.has_sps = true;
          if (nal.type == kNalTypePPS) rec.has_pps = true;
          if (nal.type == kNalTypeIDR) rec.has_idr = true;
          if (nal.type == kNalTypeSlice) rec.has_non_idr = true;
        }

        records.push_back(std::move(rec));
      }
      av_packet_unref(pkt);
    }
    av_packet_free(&pkt);
  }

  avformat_close_input(&fmt_ctx);
  avio_context_free(&avio_ctx);

  return records;
}

#endif  // RETROVUE_FFMPEG_AVAILABLE

// =========================================================================
// Test fixture
// =========================================================================
class StreamBootstrapContractTest : public ::testing::Test {};

#ifdef RETROVUE_FFMPEG_AVAILABLE

// =========================================================================
// TEST 1: INV-H264-PARAMETER-SETS — Every IDR carries SPS and PPS
// =========================================================================
// Encodes enough frames to produce at least 2 IDR frames (>1 GOP).
// Demuxes the TS output and asserts every IDR packet contains SPS+PPS.
//
// This tests the viewer's perspective: can they decode from any IDR?
// =========================================================================
TEST_F(StreamBootstrapContractTest, INV_H264_PARAMETER_SETS_EveryIdrHasSpsPps) {
  auto config = CreateTestConfig();
  config.gop_size = 10;  // Small GOP for multiple IDRs

  auto packets = EncodeAndDemux(config, 25);
  ASSERT_GT(packets.size(), 0u) << "No video packets demuxed from TS output";

  int idr_count = 0;
  for (size_t i = 0; i < packets.size(); ++i) {
    const auto& pkt = packets[i];
    if (!pkt.has_idr) continue;
    ++idr_count;

    // Diagnostic: NAL composition
    std::cout << "[DIAG] IDR packet " << i << " dts=" << pkt.dts
              << " keyframe=" << pkt.is_keyframe << " NAL types:";
    for (const auto& nal : pkt.nal_units) {
      std::cout << " " << static_cast<int>(nal.type);
    }
    std::cout << " sps=" << pkt.has_sps << " pps=" << pkt.has_pps
              << std::endl;

    EXPECT_TRUE(pkt.has_sps)
        << "INV-H264-PARAMETER-SETS VIOLATION: IDR packet " << i
        << " (dts=" << pkt.dts << ") has no SPS NAL unit in TS output";

    EXPECT_TRUE(pkt.has_pps)
        << "INV-H264-PARAMETER-SETS VIOLATION: IDR packet " << i
        << " (dts=" << pkt.dts << ") has no PPS NAL unit in TS output";
  }

  EXPECT_GE(idr_count, 2)
      << "Need at least 2 IDR frames to verify the invariant holds "
      << "beyond the initial keyframe (got " << idr_count << ")";
}

// =========================================================================
// TEST 2: INV-STREAM-JOINABLE — First frame has SPS/PPS
// =========================================================================
// Verifies the very first video packet in the TS output contains SPS+PPS.
// =========================================================================
TEST_F(StreamBootstrapContractTest, INV_STREAM_JOINABLE_FirstFrameHasParameterSets) {
  auto config = CreateTestConfig();

  auto packets = EncodeAndDemux(config, 5);
  ASSERT_GT(packets.size(), 0u) << "No video packets demuxed";

  const auto& first = packets[0];

  // Diagnostic
  std::cout << "[DIAG] First video packet: dts=" << first.dts
            << " keyframe=" << first.is_keyframe << " NAL types:";
  for (const auto& nal : first.nal_units) {
    std::cout << " " << static_cast<int>(nal.type);
  }
  std::cout << std::endl;

  EXPECT_TRUE(first.has_idr)
      << "INV-STREAM-JOINABLE VIOLATION: First video packet is not IDR";
  EXPECT_TRUE(first.has_sps)
      << "INV-STREAM-JOINABLE VIOLATION: First video packet has no SPS";
  EXPECT_TRUE(first.has_pps)
      << "INV-STREAM-JOINABLE VIOLATION: First video packet has no PPS";
}

// =========================================================================
// TEST 3: INV-STREAM-BOOTSTRAP-BOUND — SPS/PPS at least once per GOP
// =========================================================================
// Encodes 3 GOPs. Asserts SPS/PPS appears within every gop_size frames
// in the demuxed TS output.
// =========================================================================
TEST_F(StreamBootstrapContractTest, INV_STREAM_BOOTSTRAP_BOUND_SpsPpsPerGop) {
  auto config = CreateTestConfig();
  config.gop_size = 15;

  auto packets = EncodeAndDemux(config, 50);
  ASSERT_GT(packets.size(), 0u) << "No video packets demuxed";

  int frames_since_sps = 0;
  int frames_since_pps = 0;
  bool first_sps_seen = false;
  bool first_pps_seen = false;

  for (size_t i = 0; i < packets.size(); ++i) {
    const auto& pkt = packets[i];

    if (pkt.has_sps) {
      frames_since_sps = 0;
      first_sps_seen = true;
    } else {
      ++frames_since_sps;
    }

    if (pkt.has_pps) {
      frames_since_pps = 0;
      first_pps_seen = true;
    } else {
      ++frames_since_pps;
    }

    if (first_sps_seen) {
      EXPECT_LE(frames_since_sps, config.gop_size)
          << "INV-STREAM-BOOTSTRAP-BOUND VIOLATION: " << frames_since_sps
          << " frames since last SPS at packet " << i
          << " (gop_size=" << config.gop_size << ")";
    }

    if (first_pps_seen) {
      EXPECT_LE(frames_since_pps, config.gop_size)
          << "INV-STREAM-BOOTSTRAP-BOUND VIOLATION: " << frames_since_pps
          << " frames since last PPS at packet " << i
          << " (gop_size=" << config.gop_size << ")";
    }
  }

  EXPECT_TRUE(first_sps_seen) << "No SPS found in TS output";
  EXPECT_TRUE(first_pps_seen) << "No PPS found in TS output";
}

#else  // !RETROVUE_FFMPEG_AVAILABLE

TEST(StreamBootstrapContractTest, DISABLED_RequiresFFmpeg) {
  GTEST_SKIP() << "StreamBootstrap tests require RETROVUE_FFMPEG_AVAILABLE";
}

#endif  // RETROVUE_FFMPEG_AVAILABLE

}  // namespace
