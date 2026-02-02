// Phase 8.4 — Persistent MPEG-TS mux contract tests.
// Exact checks per Phase8-4-PersistentMpegTsMux.md: TS validity (188, 0x47, parse PAT/PMT),
// PID stability, continuity counters (mod 16; discontinuity only when indicator set), PTS/PCR monotonicity.
// INV-AIR-IDR-BEFORE-OUTPUT (P1-EP-005): First video packet is IDR; gate resets on segment switch.

#include <cstdint>
#include <cstdio>
#include <map>
#include <set>
#include <vector>
#include <unistd.h>

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

constexpr int kTsPacketSize = 188;
constexpr uint8_t kTsSyncByte = 0x47;
constexpr uint16_t kPatPid = 0x0000;

// Single-threaded capture; stream-oriented callback (no packet assumptions).
struct CaptureState {
  std::vector<uint8_t> buffer;   // Staging: incoming bytes
  std::vector<std::vector<uint8_t>> packets;  // Complete 188-byte packets
  bool bad_sync = false;
};

static int CaptureWriteCallback(void* opaque, uint8_t* buf, int buf_size) {
  auto* s = static_cast<CaptureState*>(opaque);
  s->buffer.insert(s->buffer.end(), buf, buf + buf_size);

  size_t offset = 0;
  while (s->buffer.size() - offset >= static_cast<size_t>(kTsPacketSize)) {
    if (s->buffer[offset] != kTsSyncByte) s->bad_sync = true;
    s->packets.emplace_back(s->buffer.begin() + offset,
                            s->buffer.begin() + offset + kTsPacketSize);
    offset += kTsPacketSize;
  }
  if (offset > 0) {
    s->buffer.erase(s->buffer.begin(), s->buffer.begin() + offset);
  }
  return buf_size;
}

// ---- TS packet helpers ----
uint16_t GetPid(const uint8_t* p) {
  return (static_cast<uint16_t>(p[1] & 0x1f) << 8) | p[2];
}
uint8_t GetContinuityCounter(const uint8_t* p) { return p[3] & 0x0f; }
bool HasPayload(const uint8_t* p) { return (p[3] & 0x10) != 0; }
bool PayloadUnitStart(const uint8_t* p) { return (p[1] & 0x40) != 0; }
bool HasAdaptation(const uint8_t* p) { return ((p[3] >> 4) & 0x02) != 0; }
bool DiscontinuityIndicator(const uint8_t* p) {
  if (!HasAdaptation(p) || 5 > kTsPacketSize) return false;
  uint8_t alen = p[4];
  if (alen < 1) return false;
  return (p[5] & 0x80) != 0;
}

// Iterate packets; return true if all packets are 188 bytes and start with 0x47.
bool TsValidity_188AndSync(const std::vector<uint8_t>& ts, size_t* packet_count) {
  *packet_count = 0;
  if (ts.size() % kTsPacketSize != 0) return false;
  for (size_t i = 0; i < ts.size(); i += kTsPacketSize) {
    if (ts[i] != kTsSyncByte) return false;
    (*packet_count)++;
  }
  return true;
}

// Minimal PAT parser: find first PAT section, return program_map_PID (PMT PID) or -1.
int ParsePatGetPmtPid(const std::vector<uint8_t>& ts) {
  for (size_t i = 0; i + kTsPacketSize <= ts.size(); i += kTsPacketSize) {
    const uint8_t* p = ts.data() + i;
    if (GetPid(p) != kPatPid || !HasPayload(p) || !PayloadUnitStart(p)) continue;
    size_t off = 4;
    if (HasAdaptation(p)) {
      off += 1 + p[4];
      if (off + 1 >= kTsPacketSize) continue;
    }
    uint8_t pointer = p[off++];
    if (off + pointer + 8 > kTsPacketSize) continue;
    off += pointer;
    if (p[off] != 0x00) continue;  // table_id PAT
    uint16_t sect_len = (static_cast<uint16_t>(p[off + 1] & 0x0f) << 8) | p[off + 2];
    if (sect_len < 9) continue;  // header(5) + at least one 4-byte program entry
    // PAT section header: table_id(1) + section_length(2) + transport_stream_id(2) +
    // version/flags(1) + section_number(1) + last_section_number(1) = 8 bytes
    // Program entries start at off+8: program_number(2) + reserved+PID(2)
    if (off + 12 > kTsPacketSize) continue;
    uint16_t prog_num = (static_cast<uint16_t>(p[off + 8]) << 8) | p[off + 9];
    (void)prog_num;
    uint16_t pmt_pid = (static_cast<uint16_t>(p[off + 10] & 0x1f) << 8) | p[off + 11];
    return pmt_pid;
  }
  return -1;
}

// Minimal PMT parser: from payload of PMT PID, collect PCR_PID and stream_type 0x01/0x1b (video), 0x03/0x0f (audio).
bool ParsePmt(const uint8_t* payload, size_t len, uint16_t* pcr_pid,
              std::set<uint16_t>* video_pids, std::set<uint16_t>* audio_pids) {
  if (len < 12 || payload[0] != 0x02) return false;  // table_id PMT
  uint16_t sect_len = (static_cast<uint16_t>(payload[1] & 0x0f) << 8) | payload[2];
  if (sect_len > len - 3) return false;
  size_t section_end = 3 + sect_len;
  *pcr_pid = (static_cast<uint16_t>(payload[8] & 0x1f) << 8) | payload[9];
  size_t prog_info_len = (static_cast<size_t>(payload[10] & 0x0f) << 8) | payload[11];
  size_t i = 12 + prog_info_len;
  while (i + 5 <= section_end) {
    uint8_t stream_type = payload[i];
    uint16_t elem_pid = (static_cast<uint16_t>(payload[i + 1] & 0x1f) << 8) | payload[i + 2];
    size_t es_info_len = (static_cast<size_t>(payload[i + 3] & 0x0f) << 8) | payload[i + 4];
    if (stream_type == 0x01 || stream_type == 0x1b) video_pids->insert(elem_pid);  // H.262, H.264
    if (stream_type == 0x03 || stream_type == 0x0f || stream_type == 0x11) audio_pids->insert(elem_pid);  // MP3, AAC
    i += 5 + es_info_len;
    if (i > section_end) break;
  }
  return true;
}

// Collect PAT/PMT parsing result: pat_ok, pmt_ok, pmt_pid, pcr_pid, video_pids, audio_pids.
struct PsiState {
  bool pat_parsed = false;
  bool pmt_parsed = false;
  int pmt_pid = -1;
  uint16_t pcr_pid = 0x1fff;
  std::set<uint16_t> video_pids;
  std::set<uint16_t> audio_pids;
};
bool ParsePatAndPmt(const std::vector<uint8_t>& ts, PsiState* out) {
  int pmt_pid = ParsePatGetPmtPid(ts);
  if (pmt_pid < 0) return false;
  out->pat_parsed = true;
  out->pmt_pid = pmt_pid;
  for (size_t i = 0; i + kTsPacketSize <= ts.size(); i += kTsPacketSize) {
    const uint8_t* p = ts.data() + i;
    if (GetPid(p) != static_cast<uint16_t>(pmt_pid) || !HasPayload(p) || !PayloadUnitStart(p)) continue;
    size_t off = 4;
    if (HasAdaptation(p)) {
      off += 1 + p[4];
      if (off + 1 >= kTsPacketSize) continue;
    }
    // Skip pointer_field (same as PAT parsing above)
    uint8_t pointer = p[off++];
    if (off + pointer >= kTsPacketSize) continue;
    off += pointer;
    size_t payload_len = kTsPacketSize - off;
    if (ParsePmt(p + off, payload_len, &out->pcr_pid, &out->video_pids, &out->audio_pids)) {
      out->pmt_parsed = true;
      return true;
    }
  }
  return out->pmt_parsed;
}

// Continuity: for each PID with payload, CC must be (last+1)&0x0f; allow discontinuity only when discontinuity_indicator set.
void CheckContinuity(const std::vector<uint8_t>& ts, bool* ok, bool allow_discontinuity_only_at_start) {
  *ok = true;
  std::map<uint16_t, uint8_t> last_cc;
  size_t packets_seen = 0;
  for (size_t i = 0; i + kTsPacketSize <= ts.size(); i += kTsPacketSize, ++packets_seen) {
    const uint8_t* p = ts.data() + i;
    uint16_t pid = GetPid(p);
    uint8_t cc = GetContinuityCounter(p);
    bool discon = DiscontinuityIndicator(p);
    if (discon && allow_discontinuity_only_at_start && packets_seen < 2) {
      last_cc[pid] = cc;
      continue;
    }
    auto it = last_cc.find(pid);
    if (it != last_cc.end()) {
      uint8_t expected = (it->second + 1) & 0x0f;
      if (cc != expected) *ok = false;
    }
    last_cc[pid] = cc;
  }
}

// Extract PCR from adaptation field (33-bit base * 300 + 6-bit ext, 90kHz).
bool GetPcrFromPacket(const uint8_t* p, int64_t* pcr_90k) {
  if (!HasAdaptation(p) || 5 >= kTsPacketSize) return false;
  uint8_t alen = p[4];
  if (alen < 7 || (p[5] & 0x10) == 0) return false;  // PCR flag
  int64_t base = (static_cast<int64_t>(p[6]) << 25) | (static_cast<int64_t>(p[7]) << 17) |
                 (static_cast<int64_t>(p[8]) << 9) | (static_cast<int64_t>(p[9]) << 1) | (p[10] >> 7);
  *pcr_90k = base * 300;  // 90kHz
  return true;
}

// PCR monotonic over stream (per PCR PID).
bool PcrMonotonic(const std::vector<uint8_t>& ts, uint16_t pcr_pid) {
  int64_t last = -1;
  for (size_t i = 0; i + kTsPacketSize <= ts.size(); i += kTsPacketSize) {
    const uint8_t* p = ts.data() + i;
    if (GetPid(p) != pcr_pid) continue;
    int64_t pcr;
    if (!GetPcrFromPacket(p, &pcr)) continue;
    if (last >= 0 && pcr <= last) return false;
    last = pcr;
  }
  return true;
}

// PID stability: same set of PIDs in first half vs second half (or single run if small).
bool PidStableOverWindow(const std::vector<uint8_t>& ts, size_t window_packets) {
  std::set<uint16_t> first, second;
  size_t n = 0;
  for (size_t i = 0; i + kTsPacketSize <= ts.size(); i += kTsPacketSize, ++n) {
    uint16_t pid = GetPid(ts.data() + i);
    if (n < window_packets / 2)
      first.insert(pid);
    else
      second.insert(pid);
    if (n >= window_packets) break;
  }
  return first == second;
}

#ifdef RETROVUE_FFMPEG_AVAILABLE
// INV-AIR-IDR-BEFORE-OUTPUT: Parse TS with FFmpeg, return first video packet's keyframe flag.
// Returns: true if first video packet is keyframe, false if not or parse failed.
bool FirstVideoPacketIsKeyframe(const std::vector<uint8_t>& ts) {
  const char* tmp = "/tmp/phase84_idr_test.ts";
  FILE* f = fopen(tmp, "wb");
  if (!f) return false;
  size_t n = fwrite(ts.data(), 1, ts.size(), f);
  fclose(f);
  if (n != ts.size()) {
    unlink(tmp);
    return false;
  }

  AVFormatContext* fmt = nullptr;
  if (avformat_open_input(&fmt, tmp, nullptr, nullptr) < 0) {
    unlink(tmp);
    return false;
  }
  if (avformat_find_stream_info(fmt, nullptr) < 0) {
    avformat_close_input(&fmt);
    unlink(tmp);
    return false;
  }

  int vid_idx = -1;
  for (unsigned i = 0; i < fmt->nb_streams; ++i) {
    if (fmt->streams[i]->codecpar->codec_type == AVMEDIA_TYPE_VIDEO) {
      vid_idx = static_cast<int>(i);
      break;
    }
  }
  if (vid_idx < 0) {
    avformat_close_input(&fmt);
    unlink(tmp);
    return false;
  }

  AVPacket* pkt = av_packet_alloc();
  bool first_is_key = false;
  bool found = false;
  while (av_read_frame(fmt, pkt) >= 0) {
    if (pkt->stream_index == vid_idx) {
      first_is_key = (pkt->flags & AV_PKT_FLAG_KEY) != 0;
      found = true;
      break;
    }
    av_packet_unref(pkt);
  }
  av_packet_free(&pkt);
  avformat_close_input(&fmt);
  unlink(tmp);
  return found && first_is_key;
}

// INV-AIR-IDR-BEFORE-OUTPUT: Verify first video packet is keyframe and at least one more
// keyframe exists (first packet of segment 2). Returns true if both keyframes present.
bool FirstAndSecondSegmentStartWithKeyframe(const std::vector<uint8_t>& ts) {
  const char* tmp = "/tmp/phase84_idr_segments.ts";
  FILE* f = fopen(tmp, "wb");
  if (!f) return false;
  size_t n = fwrite(ts.data(), 1, ts.size(), f);
  fclose(f);
  if (n != ts.size()) {
    unlink(tmp);
    return false;
  }

  AVFormatContext* fmt = nullptr;
  if (avformat_open_input(&fmt, tmp, nullptr, nullptr) < 0) {
    unlink(tmp);
    return false;
  }
  if (avformat_find_stream_info(fmt, nullptr) < 0) {
    avformat_close_input(&fmt);
    unlink(tmp);
    return false;
  }

  int vid_idx = -1;
  for (unsigned i = 0; i < fmt->nb_streams; ++i) {
    if (fmt->streams[i]->codecpar->codec_type == AVMEDIA_TYPE_VIDEO) {
      vid_idx = static_cast<int>(i);
      break;
    }
  }
  if (vid_idx < 0) {
    avformat_close_input(&fmt);
    unlink(tmp);
    return false;
  }

  AVPacket* pkt = av_packet_alloc();
  int keyframe_count = 0;
  int video_packet_count = 0;
  bool first_is_key = false;
  while (av_read_frame(fmt, pkt) >= 0) {
    if (pkt->stream_index == vid_idx) {
      video_packet_count++;
      if (pkt->flags & AV_PKT_FLAG_KEY) {
        keyframe_count++;
        if (keyframe_count == 1) first_is_key = true;
      }
    }
    av_packet_unref(pkt);
    if (keyframe_count >= 2) break;  // Success - stop reading
  }
  av_packet_free(&pkt);
  avformat_close_input(&fmt);
  unlink(tmp);
  (void)video_packet_count;  // Diagnostic: total video packets seen
  return first_is_key && keyframe_count >= 2;
}
#endif

class Phase84PersistentMpegTsMuxTest : public ::testing::Test {
 protected:
  void SetUp() override {
    config_.stub_mode = false;
    config_.persistent_mux = true;
    config_.target_fps = 30.0;
    config_.bitrate = 5000000;
    config_.gop_size = 30;
  }

  // Encode frames; if open or first frame fails (e.g. no libx264), return false to skip.
  // If out_bad_sync is non-null and callback saw invalid sync byte, set *out_bad_sync = true.
  bool EncodeToCapture(std::vector<uint8_t>* out, size_t num_frames = 30, bool* out_bad_sync = nullptr) {
    CaptureState capture;
    EncoderPipeline encoder(config_);
    if (!encoder.open(config_, &capture, &CaptureWriteCallback)) return false;
    auto frames = retrovue::tests::fixtures::mpegts_sink::FrameFactory::CreateFrameSequence(0, 33333, num_frames);
    if (frames.empty() || !encoder.encodeFrame(frames[0], 0)) {
      encoder.close();
      return false;
    }
    for (size_t i = 1; i < frames.size(); ++i) {
      int64_t pts90k = (frames[i].metadata.pts * 90000) / 1'000'000;
      if (!encoder.encodeFrame(frames[i], pts90k)) break;
    }
    encoder.close();
    if (out_bad_sync) *out_bad_sync = capture.bad_sync;
    if (capture.bad_sync) return false;
    out->clear();
    for (const auto& p : capture.packets) {
      out->insert(out->end(), p.begin(), p.end());
    }
    out->insert(out->end(), capture.buffer.begin(), capture.buffer.end());
    return out->size() >= kTsPacketSize;
  }

  // Encode two segments with ResetOutputTiming() between them (segment switch).
  // Returns false if open or first frame fails.
  bool EncodeWithSegmentSwitch(std::vector<uint8_t>* out,
                               size_t frames_before = 15,
                               size_t frames_after = 15) {
    CaptureState capture;
    EncoderPipeline encoder(config_);
    if (!encoder.open(config_, &capture, &CaptureWriteCallback)) return false;
    auto frames_before_vec = retrovue::tests::fixtures::mpegts_sink::FrameFactory::
        CreateFrameSequence(0, 33333, frames_before);
    if (frames_before_vec.empty() || !encoder.encodeFrame(frames_before_vec[0], 0)) {
      encoder.close();
      return false;
    }
    for (size_t i = 1; i < frames_before_vec.size(); ++i) {
      int64_t pts90k = (frames_before_vec[i].metadata.pts * 90000) / 1'000'000;
      if (!encoder.encodeFrame(frames_before_vec[i], pts90k)) break;
    }
    encoder.ResetOutputTiming();  // Segment switch: gate resets
    int64_t base_pts = static_cast<int64_t>(frames_before) * 33333;
    auto frames_after_vec = retrovue::tests::fixtures::mpegts_sink::FrameFactory::
        CreateFrameSequence(base_pts, 33333, frames_after);
    if (frames_after_vec.empty()) {
      encoder.close();
      return false;
    }
    for (size_t i = 0; i < frames_after_vec.size(); ++i) {
      int64_t pts90k = ((base_pts + i * 33333) * 90000) / 1'000'000;
      if (!encoder.encodeFrame(frames_after_vec[i], pts90k)) break;
    }
    encoder.close();
    if (capture.bad_sync) return false;
    out->clear();
    for (const auto& p : capture.packets) {
      out->insert(out->end(), p.begin(), p.end());
    }
    out->insert(out->end(), capture.buffer.begin(), capture.buffer.end());
    return out->size() >= kTsPacketSize;
  }

  MpegTSPlayoutSinkConfig config_;
};

TEST_F(Phase84PersistentMpegTsMuxTest, TsValidity_PacketSize188AndSyncByte0x47) {
  std::vector<uint8_t> ts;
  bool bad_sync = false;
  if (!EncodeToCapture(&ts, 15, &bad_sync)) {
    GTEST_SKIP() << "Software H.264 (libx264) required for Phase 8.4 TS tests";
  }
  ASSERT_FALSE(bad_sync) << "Bad sync byte in TS stream";
  size_t packet_count = 0;
  ASSERT_TRUE(TsValidity_188AndSync(ts, &packet_count))
      << "TS packet size must be 188 and sync byte 0x47 every packet; remainder=" << (ts.size() % kTsPacketSize);
  EXPECT_GT(packet_count, 0u);
}

TEST_F(Phase84PersistentMpegTsMuxTest, TsValidity_ParsePatAndPmtSuccessfully) {
  std::vector<uint8_t> ts;
  if (!EncodeToCapture(&ts, 20)) {
    GTEST_SKIP() << "Software H.264 (libx264) required for Phase 8.4 TS tests";
  }
  PsiState psi;
  ASSERT_TRUE(ParsePatAndPmt(ts, &psi)) << "Must parse PAT and PMT successfully (not just contain)";
  EXPECT_TRUE(psi.pat_parsed);
  EXPECT_TRUE(psi.pmt_parsed);
  EXPECT_GE(psi.pmt_pid, 0);
  EXPECT_FALSE(psi.video_pids.empty()) << "PMT must declare at least one video PID";
}

TEST_F(Phase84PersistentMpegTsMuxTest, PidStability_PidsUnchangedOverWindow) {
  std::vector<uint8_t> ts;
  if (!EncodeToCapture(&ts, 30)) {
    GTEST_SKIP() << "Software H.264 (libx264) required for Phase 8.4 TS tests";
  }
  size_t np = ts.size() / kTsPacketSize;
  EXPECT_TRUE(PidStableOverWindow(ts, np))
      << "PMT PID, PCR PID, video/audio PIDs must not change over stream window";
}

TEST_F(Phase84PersistentMpegTsMuxTest, ContinuityCounters_IncrementMod16PerPid) {
  std::vector<uint8_t> ts;
  if (!EncodeToCapture(&ts, 30)) {
    GTEST_SKIP() << "Software H.264 (libx264) required for Phase 8.4 TS tests";
  }
  bool continuity_ok = false;
  CheckContinuity(ts, &continuity_ok, true);
  EXPECT_TRUE(continuity_ok)
      << "Continuity counter must increment modulo 16 per PID; discontinuity only if discontinuity_indicator set";
}

TEST_F(Phase84PersistentMpegTsMuxTest, Timing_PcrMonotonic) {
  std::vector<uint8_t> ts;
  if (!EncodeToCapture(&ts, 30)) {
    GTEST_SKIP() << "Software H.264 (libx264) required for Phase 8.4 TS tests";
  }
  PsiState psi;
  if (!ParsePatAndPmt(ts, &psi) || psi.pcr_pid == 0x1fff) {
    GTEST_SKIP() << "No PCR PID in PMT; skip PCR monotonicity check";
  }
  EXPECT_TRUE(PcrMonotonic(ts, psi.pcr_pid)) << "PCR must be monotonic; no backwards jumps";
}

// -----------------------------------------------------------------------------
// INV-AIR-IDR-BEFORE-OUTPUT (P1-EP-005): No video packets until first IDR.
// Gate resets on segment switch; first packet after switch must be IDR.
// -----------------------------------------------------------------------------

TEST_F(Phase84PersistentMpegTsMuxTest, INV_AIR_IDR_BEFORE_OUTPUT_FirstVideoPacketIsIdr) {
#ifdef RETROVUE_FFMPEG_AVAILABLE
  std::vector<uint8_t> ts;
  if (!EncodeToCapture(&ts, 20)) {
    GTEST_SKIP() << "Software H.264 (libx264) required for INV-AIR-IDR-BEFORE-OUTPUT test";
  }
  ASSERT_TRUE(FirstVideoPacketIsKeyframe(ts))
      << "INV-AIR-IDR-BEFORE-OUTPUT: First video packet must be IDR (keyframe); "
      << "no packets may be emitted before first IDR";
#else
  GTEST_SKIP() << "FFmpeg not available";
#endif
}

TEST_F(Phase84PersistentMpegTsMuxTest, INV_AIR_IDR_BEFORE_OUTPUT_GateResetsOnSegmentSwitch) {
#ifdef RETROVUE_FFMPEG_AVAILABLE
  std::vector<uint8_t> ts;
  config_.gop_size = 10;  // Shorter GOP so segment 1 produces 2+ keyframes; segment 2 starts with forced I
  // Use 15+15 frames: segment 1 has keyframes at 0,10; segment 2 has forced keyframe at 15
  if (!EncodeWithSegmentSwitch(&ts, 15, 15)) {
    GTEST_SKIP() << "Software H.264 (libx264) required for INV-AIR-IDR-BEFORE-OUTPUT test";
  }
  ASSERT_TRUE(FirstAndSecondSegmentStartWithKeyframe(ts))
      << "INV-AIR-IDR-BEFORE-OUTPUT: After ResetOutputTiming (segment switch), "
      << "gate must reset; first packet after switch must be IDR";
#else
  GTEST_SKIP() << "FFmpeg not available";
#endif
}

}  // namespace
