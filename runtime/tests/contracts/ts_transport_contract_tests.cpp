// INV-TS-SYNC / INV-TS-CONTINUITY / INV-PCR-MONOTONIC / INV-PCR-INTERVAL
// INV-PAT-REPETITION / INV-PMT-REPETITION / INV-PCR-CLOCK-REFERENCE
// contract tests.
// See: docs/contracts/ts_transport_integrity.md
//
// These tests verify OBSERVABLE TS output properties from raw 188-byte packets.
// No FFmpeg demuxer is used for TS-layer inspection — packets are parsed
// directly from the transport stream byte structure.

#include <cstdint>
#include <cstring>
#include <iostream>
#include <map>
#include <vector>

#include <gtest/gtest.h>
#include "retrovue/playout_sinks/mpegts/EncoderPipeline.hpp"
#include "retrovue/playout_sinks/mpegts/MpegTSPlayoutSinkConfig.hpp"
#include "mpegts_sink/FrameFactory.h"

#ifdef RETROVUE_FFMPEG_AVAILABLE
extern "C" {
#include <libavcodec/avcodec.h>
#include <libavformat/avformat.h>
}
#endif

namespace {

using retrovue::playout_sinks::mpegts::EncoderPipeline;
using retrovue::playout_sinks::mpegts::MpegTSPlayoutSinkConfig;
using retrovue::tests::fixtures::mpegts_sink::FrameFactory;

// =========================================================================
// TS packet constants
// =========================================================================
constexpr size_t kTsPacketSize = 188;
constexpr uint8_t kTsSyncByte = 0x47;
constexpr uint16_t kPatPid = 0x0000;

// =========================================================================
// Parsed TS packet info (raw packet inspection — no FFmpeg demuxer)
// =========================================================================
struct TsPacketInfo {
  size_t offset;               // byte offset in capture buffer
  uint16_t pid;                // 13-bit PID
  uint8_t continuity_counter;  // 4-bit CC
  bool has_adaptation_field;
  bool has_payload;
  bool payload_unit_start;
  bool has_pcr;
  int64_t pcr_base;           // 33-bit PCR base (90kHz ticks)
  uint16_t pcr_ext;           // 9-bit PCR extension
};

// Parse a single 188-byte TS packet header.
// Returns false if sync byte is not 0x47.
bool ParseTsPacket(const uint8_t* data, size_t offset, TsPacketInfo& info) {
  info.offset = offset;
  info.has_pcr = false;
  info.pcr_base = 0;
  info.pcr_ext = 0;

  if (data[0] != kTsSyncByte) return false;

  // Bytes 1-2: TEI(1) PUSI(1) priority(1) PID(13)
  info.payload_unit_start = (data[1] & 0x40) != 0;
  info.pid = static_cast<uint16_t>(((data[1] & 0x1F) << 8) | data[2]);

  // Byte 3: scrambling(2) adaptation_field_control(2) CC(4)
  uint8_t adaptation_field_control = (data[3] >> 4) & 0x03;
  info.continuity_counter = data[3] & 0x0F;

  info.has_adaptation_field = (adaptation_field_control & 0x02) != 0;
  info.has_payload = (adaptation_field_control & 0x01) != 0;

  // Parse adaptation field for PCR if present
  if (info.has_adaptation_field && kTsPacketSize > 4) {
    uint8_t af_length = data[4];
    if (af_length > 0 && af_length <= 183) {
      uint8_t af_flags = data[5];
      bool pcr_flag = (af_flags & 0x10) != 0;
      if (pcr_flag && af_length >= 7) {
        // PCR: 6 bytes starting at data[6]
        // PCR_base: 33 bits (bytes 6-10, top bit of byte 10)
        // reserved: 6 bits
        // PCR_ext: 9 bits
        info.has_pcr = true;
        info.pcr_base = (static_cast<int64_t>(data[6]) << 25) |
                        (static_cast<int64_t>(data[7]) << 17) |
                        (static_cast<int64_t>(data[8]) << 9) |
                        (static_cast<int64_t>(data[9]) << 1) |
                        (static_cast<int64_t>(data[10]) >> 7);
        info.pcr_ext = static_cast<uint16_t>(
            ((data[10] & 0x01) << 8) | data[11]);
      }
    }
  }

  return true;
}

// Parse all TS packets from a captured buffer.
std::vector<TsPacketInfo> ParseAllTsPackets(const std::vector<uint8_t>& buffer) {
  std::vector<TsPacketInfo> packets;
  size_t num_packets = buffer.size() / kTsPacketSize;
  packets.reserve(num_packets);

  for (size_t i = 0; i < num_packets; ++i) {
    TsPacketInfo info;
    size_t offset = i * kTsPacketSize;
    if (ParseTsPacket(buffer.data() + offset, offset, info)) {
      packets.push_back(info);
    } else {
      // Still record it — test will catch the bad sync byte
      info.offset = offset;
      info.pid = 0xFFFF;
      info.continuity_counter = 0;
      info.has_adaptation_field = false;
      info.has_payload = false;
      info.payload_unit_start = false;
      info.has_pcr = false;
      info.pcr_base = 0;
      info.pcr_ext = 0;
      packets.push_back(info);
    }
  }

  return packets;
}

// Parse PAT to extract PMT PID.
// PAT payload starts after TS header (+ pointer field if PUSI).
// Returns 0xFFFF if not found.
uint16_t ExtractPmtPidFromPat(const uint8_t* ts_packet) {
  // Skip TS header (4 bytes)
  size_t pos = 4;

  // Check adaptation field
  uint8_t afc = (ts_packet[3] >> 4) & 0x03;
  if (afc & 0x02) {
    uint8_t af_len = ts_packet[4];
    pos = 5 + af_len;
  }

  // PUSI: pointer field
  bool pusi = (ts_packet[1] & 0x40) != 0;
  if (pusi) {
    if (pos >= kTsPacketSize) return 0xFFFF;
    uint8_t pointer = ts_packet[pos];
    pos += 1 + pointer;
  }

  if (pos + 8 >= kTsPacketSize) return 0xFFFF;

  // PAT section: table_id(1) flags+length(2) tsid(2) version(1) section(1) last_section(1)
  // then 4-byte entries: program_number(2) + reserved(3bits) + PID(13bits)
  uint8_t table_id = ts_packet[pos];
  if (table_id != 0x00) return 0xFFFF;  // Not a PAT

  uint16_t section_length = static_cast<uint16_t>(
      ((ts_packet[pos + 1] & 0x0F) << 8) | ts_packet[pos + 2]);
  pos += 3;  // past table_id + section_length

  // Skip transport_stream_id(2) + version/flags(1) + section_number(1) + last_section_number(1)
  pos += 5;

  // Program entries: section_length - 5 (header) - 4 (CRC) = usable bytes
  int entries_len = static_cast<int>(section_length) - 5 - 4;
  if (entries_len < 4) return 0xFFFF;

  // Read first non-NIT entry
  for (int i = 0; i < entries_len; i += 4) {
    if (pos + 3 >= kTsPacketSize) break;
    uint16_t program_number = static_cast<uint16_t>(
        (ts_packet[pos] << 8) | ts_packet[pos + 1]);
    uint16_t pid = static_cast<uint16_t>(
        ((ts_packet[pos + 2] & 0x1F) << 8) | ts_packet[pos + 3]);
    pos += 4;

    if (program_number != 0) {
      return pid;  // First program's PMT PID
    }
  }

  return 0xFFFF;
}

// =========================================================================
// Capture infrastructure (reused from stream_bootstrap_contract_tests.cpp)
// =========================================================================
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
  config.persistent_mux = true;  // Test the harder path (no pat_pmt_at_frames)
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

// =========================================================================
// Encode video+audio and capture raw TS bytes.
// Returns the CaptureState with raw MPEG-TS output.
// =========================================================================
CaptureState EncodeAndCapture(MpegTSPlayoutSinkConfig& config, int num_frames) {
  CaptureState ts_capture;
  EncoderPipeline pipeline(config);

  if (!pipeline.open(config, &ts_capture, CaptureWriteCallback)) {
    return ts_capture;
  }
  pipeline.SetAudioLivenessEnabled(false);

  constexpr int64_t kFrameDurationUs = 33367;  // ~30fps (30000/1001)
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
  return ts_capture;
}

#endif  // RETROVUE_FFMPEG_AVAILABLE

// =========================================================================
// Test fixture
// =========================================================================
class TsTransportContractTest : public ::testing::Test {};

#ifdef RETROVUE_FFMPEG_AVAILABLE

// =========================================================================
// TEST 1: INV-TS-SYNC — Every TS packet starts with sync byte 0x47
// =========================================================================
TEST_F(TsTransportContractTest, INV_TS_SYNC_AllPacketsStartWithSyncByte) {
  auto config = CreateTestConfig();
  auto capture = EncodeAndCapture(config, 90);

  ASSERT_GT(capture.buffer.size(), kTsPacketSize)
      << "No TS data captured";
  ASSERT_EQ(capture.buffer.size() % kTsPacketSize, 0u)
      << "Captured buffer is not aligned to 188-byte TS packets";

  size_t num_packets = capture.buffer.size() / kTsPacketSize;
  for (size_t i = 0; i < num_packets; ++i) {
    EXPECT_EQ(capture.buffer[i * kTsPacketSize], kTsSyncByte)
        << "INV-TS-SYNC VIOLATION: Packet " << i
        << " at offset " << (i * kTsPacketSize)
        << " starts with 0x" << std::hex
        << static_cast<int>(capture.buffer[i * kTsPacketSize])
        << " instead of 0x47";
  }

  std::cout << "[DIAG] INV-TS-SYNC: " << num_packets
            << " packets verified, all start with 0x47" << std::endl;
}

// =========================================================================
// TEST 2: INV-TS-CONTINUITY — Per-PID CC increments mod 16
// =========================================================================
TEST_F(TsTransportContractTest, INV_TS_CONTINUITY_PerPidCounterIncrements) {
  auto config = CreateTestConfig();
  auto capture = EncodeAndCapture(config, 90);

  ASSERT_GT(capture.buffer.size(), kTsPacketSize);

  auto packets = ParseAllTsPackets(capture.buffer);
  ASSERT_GT(packets.size(), 0u);

  // Track last CC per PID
  std::map<uint16_t, int> last_cc;  // PID → last CC (-1 = not seen)
  std::map<uint16_t, int> packet_count;

  for (const auto& pkt : packets) {
    if (pkt.pid == 0xFFFF) continue;  // Unparseable packet

    auto it = last_cc.find(pkt.pid);
    if (it == last_cc.end()) {
      // First packet for this PID
      last_cc[pkt.pid] = pkt.continuity_counter;
      packet_count[pkt.pid] = 1;
      continue;
    }

    uint8_t prev_cc = static_cast<uint8_t>(it->second);
    uint8_t expected_cc = (prev_cc + 1) % 16;

    // Duplicate CC is valid for adaptation-only packets
    bool is_duplicate = (pkt.continuity_counter == prev_cc);
    bool is_sequential = (pkt.continuity_counter == expected_cc);

    if (pkt.has_payload) {
      EXPECT_TRUE(is_sequential || is_duplicate)
          << "INV-TS-CONTINUITY VIOLATION: PID 0x" << std::hex << pkt.pid
          << std::dec << " CC=" << static_cast<int>(pkt.continuity_counter)
          << " expected " << static_cast<int>(expected_cc)
          << " (prev=" << static_cast<int>(prev_cc) << ")"
          << " at offset " << pkt.offset;
    }

    it->second = pkt.continuity_counter;
    packet_count[pkt.pid]++;
  }

  std::cout << "[DIAG] INV-TS-CONTINUITY: Tracked " << last_cc.size()
            << " PIDs:";
  for (const auto& [pid, count] : packet_count) {
    std::cout << " 0x" << std::hex << pid << std::dec << "(" << count << ")";
  }
  std::cout << std::endl;
}

// =========================================================================
// TEST 3: INV-PCR-MONOTONIC — PCR values never decrease
// =========================================================================
TEST_F(TsTransportContractTest, INV_PCR_MONOTONIC_PcrNeverDecreases) {
  auto config = CreateTestConfig();
  auto capture = EncodeAndCapture(config, 90);

  ASSERT_GT(capture.buffer.size(), kTsPacketSize);

  auto packets = ParseAllTsPackets(capture.buffer);

  std::map<uint16_t, int64_t> last_pcr;  // PID → last PCR base
  int pcr_count = 0;

  for (const auto& pkt : packets) {
    if (!pkt.has_pcr) continue;
    ++pcr_count;

    auto it = last_pcr.find(pkt.pid);
    if (it == last_pcr.end()) {
      last_pcr[pkt.pid] = pkt.pcr_base;
      continue;
    }

    EXPECT_GE(pkt.pcr_base, it->second)
        << "INV-PCR-MONOTONIC VIOLATION: PID 0x" << std::hex << pkt.pid
        << std::dec << " PCR decreased from " << it->second
        << " to " << pkt.pcr_base
        << " at offset " << pkt.offset;

    it->second = pkt.pcr_base;
  }

  EXPECT_GE(pcr_count, 2)
      << "Need at least 2 PCR packets to verify monotonicity";

  std::cout << "[DIAG] INV-PCR-MONOTONIC: " << pcr_count
            << " PCR packets verified" << std::endl;
}

// =========================================================================
// TEST 4: INV-PCR-INTERVAL — PCR repeats within 133ms (100ms spec + tolerance)
// =========================================================================
TEST_F(TsTransportContractTest, INV_PCR_INTERVAL_PcrRepeatsWithin100ms) {
  auto config = CreateTestConfig();
  auto capture = EncodeAndCapture(config, 90);

  ASSERT_GT(capture.buffer.size(), kTsPacketSize);

  auto packets = ParseAllTsPackets(capture.buffer);

  // 133ms in 90kHz ticks = 12000 (spec is 100ms = 9000, with 33ms tolerance)
  constexpr int64_t kMaxPcrGap90k = 12000;

  std::map<uint16_t, int64_t> last_pcr;
  int pcr_pair_count = 0;

  for (const auto& pkt : packets) {
    if (!pkt.has_pcr) continue;

    auto it = last_pcr.find(pkt.pid);
    if (it == last_pcr.end()) {
      last_pcr[pkt.pid] = pkt.pcr_base;
      continue;
    }

    int64_t gap = pkt.pcr_base - it->second;
    ++pcr_pair_count;

    EXPECT_LE(gap, kMaxPcrGap90k)
        << "INV-PCR-INTERVAL VIOLATION: PID 0x" << std::hex << pkt.pid
        << std::dec << " PCR gap " << gap << " ticks ("
        << (gap * 1000 / 90000) << "ms) exceeds 133ms limit"
        << " at offset " << pkt.offset;

    it->second = pkt.pcr_base;
  }

  EXPECT_GE(pcr_pair_count, 2)
      << "Need at least 2 PCR intervals to verify";

  std::cout << "[DIAG] INV-PCR-INTERVAL: " << pcr_pair_count
            << " PCR intervals verified (max allowed gap: "
            << (kMaxPcrGap90k * 1000 / 90000) << "ms)" << std::endl;
}

// =========================================================================
// TEST 5: INV-PAT-REPETITION — PAT repeats within 500ms
// =========================================================================
TEST_F(TsTransportContractTest, INV_PAT_REPETITION_PatRepeatsWithin500ms) {
  auto config = CreateTestConfig();
  auto capture = EncodeAndCapture(config, 90);

  ASSERT_GT(capture.buffer.size(), kTsPacketSize);

  auto packets = ParseAllTsPackets(capture.buffer);

  // 500ms in 90kHz ticks = 45000
  constexpr int64_t kMaxPatGap90k = 45000;

  // Track running PCR estimate and PAT appearances
  int64_t current_pcr = -1;
  int64_t last_pat_pcr = -1;
  int pat_count = 0;

  for (const auto& pkt : packets) {
    // Update running PCR estimate from any PCR-carrying packet
    if (pkt.has_pcr) {
      current_pcr = pkt.pcr_base;
    }

    // Check for PAT (PID 0x0000 with PUSI = start of new section)
    if (pkt.pid == kPatPid && pkt.payload_unit_start && current_pcr >= 0) {
      ++pat_count;

      if (last_pat_pcr >= 0) {
        int64_t gap = current_pcr - last_pat_pcr;

        EXPECT_LE(gap, kMaxPatGap90k)
            << "INV-PAT-REPETITION VIOLATION: PAT gap " << gap
            << " ticks (" << (gap * 1000 / 90000) << "ms)"
            << " exceeds 500ms limit at offset " << pkt.offset;
      }

      last_pat_pcr = current_pcr;
    }
  }

  EXPECT_GE(pat_count, 2)
      << "Need at least 2 PAT sections to verify repetition";

  std::cout << "[DIAG] INV-PAT-REPETITION: " << pat_count
            << " PAT sections found" << std::endl;
}

// =========================================================================
// TEST 6: INV-PMT-REPETITION — PMT repeats within 500ms
// =========================================================================
TEST_F(TsTransportContractTest, INV_PMT_REPETITION_PmtRepeatsWithin500ms) {
  auto config = CreateTestConfig();
  auto capture = EncodeAndCapture(config, 90);

  ASSERT_GT(capture.buffer.size(), kTsPacketSize);

  auto packets = ParseAllTsPackets(capture.buffer);

  // First, find PMT PID from the first PAT
  uint16_t pmt_pid = 0xFFFF;
  for (size_t i = 0; i < packets.size(); ++i) {
    if (packets[i].pid == kPatPid && packets[i].payload_unit_start) {
      pmt_pid = ExtractPmtPidFromPat(
          capture.buffer.data() + packets[i].offset);
      if (pmt_pid != 0xFFFF) break;
    }
  }

  ASSERT_NE(pmt_pid, 0xFFFF)
      << "Could not find PMT PID from PAT";

  std::cout << "[DIAG] PMT PID: 0x" << std::hex << pmt_pid
            << std::dec << std::endl;

  // 500ms in 90kHz ticks = 45000
  constexpr int64_t kMaxPmtGap90k = 45000;

  int64_t current_pcr = -1;
  int64_t last_pmt_pcr = -1;
  int pmt_count = 0;

  for (const auto& pkt : packets) {
    if (pkt.has_pcr) {
      current_pcr = pkt.pcr_base;
    }

    if (pkt.pid == pmt_pid && pkt.payload_unit_start && current_pcr >= 0) {
      ++pmt_count;

      if (last_pmt_pcr >= 0) {
        int64_t gap = current_pcr - last_pmt_pcr;

        EXPECT_LE(gap, kMaxPmtGap90k)
            << "INV-PMT-REPETITION VIOLATION: PMT gap " << gap
            << " ticks (" << (gap * 1000 / 90000) << "ms)"
            << " exceeds 500ms limit at offset " << pkt.offset;
      }

      last_pmt_pcr = current_pcr;
    }
  }

  EXPECT_GE(pmt_count, 2)
      << "Need at least 2 PMT sections to verify repetition";

  std::cout << "[DIAG] INV-PMT-REPETITION: " << pmt_count
            << " PMT sections found" << std::endl;
}

// =========================================================================
// TEST 7: INV-PCR-CLOCK-REFERENCE — PCR tracks media timeline
// =========================================================================
TEST_F(TsTransportContractTest, INV_PCR_CLOCK_REFERENCE_PcrTracksMediaTimeline) {
  auto config = CreateTestConfig();
  constexpr int kNumFrames = 90;  // 3 seconds at 30fps
  auto capture = EncodeAndCapture(config, kNumFrames);

  ASSERT_GT(capture.buffer.size(), kTsPacketSize);

  auto packets = ParseAllTsPackets(capture.buffer);

  // Find first and last PCR values
  int64_t first_pcr = -1;
  int64_t last_pcr = -1;

  for (const auto& pkt : packets) {
    if (!pkt.has_pcr) continue;
    if (first_pcr < 0) first_pcr = pkt.pcr_base;
    last_pcr = pkt.pcr_base;
  }

  ASSERT_GE(first_pcr, 0) << "No PCR packets found";
  ASSERT_GT(last_pcr, first_pcr) << "Need at least 2 distinct PCR values";

  int64_t observed_range = last_pcr - first_pcr;

  // Expected: 3 seconds = 270000 ticks at 90kHz
  // Using 30000/1001 fps: 90 frames * (1001/30000) = 3.003s = 270270 ticks
  constexpr int64_t kExpectedRange90k = 270270;
  constexpr int64_t kTolerance90k = kExpectedRange90k * 2 / 100;  // ±2%

  EXPECT_GE(observed_range, kExpectedRange90k - kTolerance90k)
      << "INV-PCR-CLOCK-REFERENCE VIOLATION: PCR range " << observed_range
      << " ticks is below expected " << kExpectedRange90k
      << " - " << kTolerance90k << " (2% tolerance)";

  EXPECT_LE(observed_range, kExpectedRange90k + kTolerance90k)
      << "INV-PCR-CLOCK-REFERENCE VIOLATION: PCR range " << observed_range
      << " ticks exceeds expected " << kExpectedRange90k
      << " + " << kTolerance90k << " (2% tolerance)";

  double observed_seconds = static_cast<double>(observed_range) / 90000.0;
  double expected_seconds = static_cast<double>(kExpectedRange90k) / 90000.0;
  double drift_pct = 100.0 * std::abs(observed_seconds - expected_seconds)
                     / expected_seconds;

  std::cout << "[DIAG] INV-PCR-CLOCK-REFERENCE: observed="
            << observed_range << " ticks (" << observed_seconds << "s)"
            << " expected=" << kExpectedRange90k << " ticks ("
            << expected_seconds << "s)"
            << " drift=" << drift_pct << "%" << std::endl;
}

#else  // !RETROVUE_FFMPEG_AVAILABLE

TEST(TsTransportContractTest, DISABLED_RequiresFFmpeg) {
  GTEST_SKIP() << "TsTransport tests require RETROVUE_FFMPEG_AVAILABLE";
}

#endif  // RETROVUE_FFMPEG_AVAILABLE

}  // namespace
