// Repository: Retrovue-playout
// Component: Mux Interleaver
// Purpose: Cross-stream DTS-ordered packet interleaving for MPEG-TS muxing.
// See: docs/contracts/mux_interleaver.md
// Copyright (c) 2025 RetroVue

#ifndef RETROVUE_PLAYOUT_SINKS_MPEGTS_MUX_INTERLEAVER_HPP_
#define RETROVUE_PLAYOUT_SINKS_MPEGTS_MUX_INTERLEAVER_HPP_

#include <cstdint>
#include <climits>
#include <functional>
#include <iostream>
#include <queue>
#include <unordered_map>
#include <vector>

#ifdef RETROVUE_FFMPEG_AVAILABLE
extern "C" {
#include <libavcodec/avcodec.h>
}
#endif

namespace retrovue::playout_sinks::mpegts {

#ifdef RETROVUE_FFMPEG_AVAILABLE

// MuxInterleaver buffers encoded packets from video and audio encoders
// and drains them in DTS order.  Owned by the mux loop (e.g.
// MpegTSOutputSink), NOT by the encoder.  This separation keeps
// encoding concerns (EncoderPipeline) separate from mux discipline.
//
// INV-MUX-WRITE-ORDER: Output is globally DTS-ascending across all
//   streams.  Flush() drains only up to a safe watermark —
//   min(latest_video_dts, latest_audio_dts) — so a stream that is
//   ahead never overtakes a stream whose encoder hasn't delivered yet.
// INV-MUX-PER-STREAM-DTS-MONOTONIC: Per-stream DTS must be non-decreasing.
//   Packets that regress within their own stream are dropped.
// INV-MUX-STARTUP-HOLDOFF: Flush blocked until both streams observed.
class MuxInterleaver {
 public:
  struct MuxPacket {
    AVPacket* pkt;       // Cloned packet (MuxInterleaver owns until flush)
    int64_t dts_90k;     // DTS rescaled to 90kHz for cross-stream ordering
    int stream_index;    // 0=video, 1=audio (typically)
  };

  // Called for each packet during Flush(), in DTS order.
  // The callee should write the packet to the muxer (e.g. via
  // EncoderPipeline::WriteMuxPacket).  MuxInterleaver frees the
  // clone shell after this callback returns.
  using WritePacketFn = std::function<void(AVPacket* pkt, int64_t dts_90k)>;

  explicit MuxInterleaver(WritePacketFn write_fn)
      : write_fn_(std::move(write_fn)) {}

  ~MuxInterleaver() { Reset(); }

  MuxInterleaver(const MuxInterleaver&) = delete;
  MuxInterleaver& operator=(const MuxInterleaver&) = delete;

  // Enqueue a cloned packet.  Takes ownership of pkt.
  void Enqueue(AVPacket* pkt, int64_t dts_90k, int stream_index) {
    if (stream_index == 0) {
      first_video_seen_ = true;
      if (dts_90k > latest_video_dts_) latest_video_dts_ = dts_90k;
    }
    if (stream_index == 1) {
      first_audio_seen_ = true;
      if (dts_90k > latest_audio_dts_) latest_audio_dts_ = dts_90k;
    }
    buffer_.push(MuxPacket{pkt, dts_90k, stream_index});
  }

  // Drain buffered packets in DTS order up to the safe watermark.
  //
  // INV-MUX-WRITE-ORDER: The watermark is min(latest_video_dts,
  // latest_audio_dts).  Packets beyond this point are held — the
  // other stream's encoder may not have delivered packets in that
  // range yet (e.g. AAC encoder delay).  This guarantees globally
  // ascending DTS at the write callback.
  //
  // INV-MUX-STARTUP-HOLDOFF: If startup holdoff is active and EITHER
  // stream is missing, Flush is a no-op.
  //
  // INV-MUX-PER-STREAM-DTS-MONOTONIC: Packets that regress within
  // their own stream are dropped.
  void Flush() {
    FlushInternal(false);
  }

  // Drain ALL remaining packets in DTS order, ignoring the watermark.
  // Used at session shutdown when no more packets will arrive.
  void DrainAll() {
    FlushInternal(true);
  }

  // INV-MUX-STARTUP-HOLDOFF: Enable/disable startup holdoff.
  // When enabled, Flush() is a no-op until both audio and video
  // packets have been enqueued.
  void SetStartupHoldoff(bool enabled) {
    startup_holdoff_active_ = enabled;
  }

  bool HasVideoPacket() const { return first_video_seen_; }
  bool HasAudioPacket() const { return first_audio_seen_; }
  bool IsEmpty() const { return buffer_.empty(); }
  size_t Size() const { return buffer_.size(); }

  // Release all buffered packets without writing.
  void Reset() {
    while (!buffer_.empty()) {
      MuxPacket mp = buffer_.top();
      buffer_.pop();
      av_packet_free(&mp.pkt);
    }
    first_video_seen_ = false;
    first_audio_seen_ = false;
    latest_video_dts_ = INT64_MIN;
    latest_audio_dts_ = INT64_MIN;
    last_dts_by_stream_.clear();
  }

 private:
  void FlushInternal(bool drain_all) {
    if (startup_holdoff_active_ && (!first_video_seen_ || !first_audio_seen_)) {
      return;  // Hold all packets until both streams observed
    }

    // INV-MUX-WRITE-ORDER: Compute the safe drainage watermark.
    // Only drain packets whose DTS <= min(latest_video, latest_audio).
    // This prevents writing ahead of a stream whose encoder hasn't
    // delivered yet (e.g. AAC priming delay shifts audio one frame).
    int64_t watermark = INT64_MAX;
    if (!drain_all) {
      if (first_video_seen_ && latest_video_dts_ != INT64_MIN)
        watermark = std::min(watermark, latest_video_dts_);
      if (first_audio_seen_ && latest_audio_dts_ != INT64_MIN)
        watermark = std::min(watermark, latest_audio_dts_);
    }

    while (!buffer_.empty()) {
      const MuxPacket& top = buffer_.top();
      if (top.dts_90k > watermark) break;  // Hold — other stream hasn't caught up

      MuxPacket mp = top;
      buffer_.pop();

      // Per-stream monotonicity check — only compare against same stream
      int64_t& last_stream_dts = last_dts_by_stream_[mp.stream_index];
      if (last_stream_dts != INT64_MIN && mp.dts_90k < last_stream_dts) {
        std::cerr << "[MuxInterleaver] INV-MUX-PER-STREAM-DTS-MONOTONIC VIOLATION: "
                  << "stream=" << mp.stream_index
                  << " dts_90k=" << mp.dts_90k
                  << " < last_stream_dts=" << last_stream_dts
                  << " — DROPPING packet (delta="
                  << (mp.dts_90k - last_stream_dts) << ")"
                  << std::endl;
        av_packet_free(&mp.pkt);
        continue;
      }
      last_stream_dts = mp.dts_90k;

      write_fn_(mp.pkt, mp.dts_90k);
      av_packet_free(&mp.pkt);
    }
  }

  struct MuxPacketGreater {
    bool operator()(const MuxPacket& a, const MuxPacket& b) const {
      if (a.dts_90k != b.dts_90k) return a.dts_90k > b.dts_90k;  // min-heap
      return a.stream_index > b.stream_index;  // video (0) before audio (1) on tie
    }
  };

  std::priority_queue<MuxPacket, std::vector<MuxPacket>, MuxPacketGreater> buffer_;
  WritePacketFn write_fn_;
  bool startup_holdoff_active_{false};
  bool first_video_seen_{false};
  bool first_audio_seen_{false};
  int64_t latest_video_dts_{INT64_MIN};
  int64_t latest_audio_dts_{INT64_MIN};
  // Per-stream last DTS — only enforce monotonicity within each stream
  std::unordered_map<int, int64_t> last_dts_by_stream_;
};

#endif  // RETROVUE_FFMPEG_AVAILABLE

}  // namespace retrovue::playout_sinks::mpegts

#endif  // RETROVUE_PLAYOUT_SINKS_MPEGTS_MUX_INTERLEAVER_HPP_
