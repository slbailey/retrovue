// AIR vNext — MpegTsEncoder implementation.
//
// Minimal transplant of runtime/src/playout_sinks/mpegts/EncoderPipeline.cpp
// with the paths listed in the header's design lineage dropped. See that
// header for the full drop list.
//
// Ported verbatim (with namespace swap):
//   - AVIOWriteThunk + HandleAVIOWrite
//   - EnforceMonotonicDts
//   - Internal MuxInterleaver wiring with startup holdoff
//   - IDR keyframe gate (first_frame_encoded_ / first_keyframe_emitted_)
//   - Video encode loop shape (send frame, receive packets loop)
//   - Audio encode loop shape with AAC frame_size buffering and the
//     sample-counter PTS (INV-AUDIO-SAMPLE-CLOCK)
//   - AAC priming-packet drop on negative DTS

#include "mpeg_ts_encoder.hpp"
#include "mux_interleaver.hpp"

#include <cstring>
#include <iostream>
#include <vector>

extern "C" {
#include <libavcodec/avcodec.h>
#include <libavformat/avformat.h>
#include <libavutil/avutil.h>
#include <libavutil/channel_layout.h>
#include <libavutil/dict.h>
#include <libavutil/mathematics.h>
#include <libavutil/opt.h>
#include <libavutil/samplefmt.h>
}

namespace retrovue::air {

// ---------------------------------------------------------------------------
// PIMPL
// ---------------------------------------------------------------------------
struct MpegTsEncoder::Impl {
  // Config
  MpegTsEncoderConfig cfg{};
  BytesOutCallback bytes_out;

  // libav state
  AVFormatContext* format_ctx = nullptr;
  AVStream* video_stream = nullptr;
  AVStream* audio_stream = nullptr;
  AVCodecContext* video_codec_ctx = nullptr;
  AVCodecContext* audio_codec_ctx = nullptr;
  AVFrame* video_frame = nullptr;
  AVFrame* audio_frame = nullptr;
  AVPacket* packet = nullptr;
  AVIOContext* custom_avio_ctx = nullptr;
  AVDictionary* muxer_opts = nullptr;

  bool header_written = false;
  bool codec_opened = false;
  bool initialized = false;

  // IDR gate (INV-AIR-IDR-BEFORE-OUTPUT)
  bool first_frame_encoded = false;
  bool first_keyframe_emitted = false;

  // Per-stream monotonic DTS/PTS tracking.
  int64_t last_video_mux_dts = AV_NOPTS_VALUE;
  int64_t last_video_mux_pts = AV_NOPTS_VALUE;
  int64_t last_audio_mux_dts = AV_NOPTS_VALUE;
  int64_t last_audio_mux_pts = AV_NOPTS_VALUE;
  int64_t last_video_input_pts = AV_NOPTS_VALUE;  // codec-timebase monotonicity

  // Audio buffering (INV-AUDIO-HOUSE-FORMAT-001 style): pack remainders from
  // one call into the next so AAC sees exactly frame_size samples per frame.
  std::vector<int16_t> audio_remainder;  // S16 interleaved
  int audio_remainder_samples = 0;

  // INV-AUDIO-SAMPLE-CLOCK: sole PTS authority for audio chunks.
  int64_t audio_encode_sample_counter = 0;

  // Internal interleaver. Holds packets until both streams observed.
  std::unique_ptr<MuxInterleaver> interleaver;

  // ----- AVIO byte callback (ported verbatim with namespace swap) -----
  static int AVIOWriteThunk(void* opaque, const uint8_t* buf, int buf_size) {
    if (opaque == nullptr) return -1;
    auto* impl = reinterpret_cast<Impl*>(opaque);
    return impl->HandleAVIOWrite(buf, buf_size);
  }

  int HandleAVIOWrite(const uint8_t* buf, int buf_size) {
    if (!bytes_out) return -1;
    return bytes_out(buf, buf_size);
  }

  // ----- Per-stream monotonic DTS enforcement (ported as-is) -----
  void EnforceMonotonicDts() {
    if (!packet) return;
    bool is_video = video_stream && packet->stream_index == video_stream->index;
    int64_t& last_dts = is_video ? last_video_mux_dts : last_audio_mux_dts;
    int64_t& last_pts = is_video ? last_video_mux_pts : last_audio_mux_pts;

    int64_t dts = packet->dts;
    int64_t pts = packet->pts;

    if (last_dts != AV_NOPTS_VALUE && dts != AV_NOPTS_VALUE && dts <= last_dts)
      dts = last_dts + 1;
    if (last_pts != AV_NOPTS_VALUE && pts != AV_NOPTS_VALUE && pts <= last_pts)
      pts = last_pts + 1;
    if (pts != AV_NOPTS_VALUE && dts != AV_NOPTS_VALUE && pts < dts) pts = dts;

    packet->dts = dts;
    packet->pts = pts;
    if (dts != AV_NOPTS_VALUE) last_dts = dts;
    if (pts != AV_NOPTS_VALUE) last_pts = pts;
  }

  // ----- EmitPacket (simplified): clone + enqueue into interleaver. -----
  void EmitPacket() {
    if (!packet || !format_ctx || !interleaver) return;
    AVPacket* cloned = av_packet_clone(packet);
    if (!cloned) {
      std::cerr << "[MpegTsEncoder] av_packet_clone failed" << std::endl;
      return;
    }
    int64_t dts_90k = 0;
    if (cloned->dts != AV_NOPTS_VALUE) {
      bool is_video = (video_stream && cloned->stream_index == video_stream->index);
      AVRational stream_tb;
      if (is_video) {
        stream_tb = video_stream->time_base;
      } else if (audio_stream && cloned->stream_index == audio_stream->index) {
        stream_tb = audio_stream->time_base;
      } else {
        stream_tb = {1, 90000};
      }
      dts_90k = av_rescale_q(cloned->dts, stream_tb, {1, 90000});
    }
    interleaver->Enqueue(cloned, dts_90k, cloned->stream_index);
  }

  // Writer used by the interleaver: feed packet to av_interleaved_write_frame.
  void WriteMuxPacket(AVPacket* pkt) {
    if (!pkt || !format_ctx) return;
    av_interleaved_write_frame(format_ctx, pkt);
    if (format_ctx->pb) avio_flush(format_ctx->pb);
  }

  // ----- Setup -----
  bool Open(const MpegTsEncoderConfig& config, BytesOutCallback cb) {
    if (initialized) return true;
    cfg = config;
    bytes_out = std::move(cb);
    if (!bytes_out) {
      std::cerr << "[MpegTsEncoder] Open: bytes_out callback is null" << std::endl;
      return false;
    }
    if (cfg.video_width <= 0 || cfg.video_height <= 0 ||
        cfg.video_fps_num <= 0 || cfg.video_fps_den <= 0 ||
        cfg.audio_sample_rate <= 0 || cfg.audio_channels <= 0) {
      std::cerr << "[MpegTsEncoder] Open: invalid config" << std::endl;
      return false;
    }

    av_log_set_level(AV_LOG_ERROR);

    // --- Video codec: libx264 only (no NVENC) ---
    const AVCodec* vcodec = avcodec_find_encoder_by_name("libx264");
    if (!vcodec) {
      std::cerr << "[MpegTsEncoder] libx264 encoder not found" << std::endl;
      return false;
    }

    // --- Audio codec: AAC ---
    const AVCodec* acodec = avcodec_find_encoder_by_name("aac");
    if (!acodec) acodec = avcodec_find_encoder(AV_CODEC_ID_AAC);
    if (!acodec) {
      std::cerr << "[MpegTsEncoder] AAC encoder not found" << std::endl;
      return false;
    }

    // --- Format context: MPEG-TS ---
    int ret = avformat_alloc_output_context2(&format_ctx, nullptr, "mpegts",
                                             "dummy://");
    if (ret < 0 || !format_ctx) {
      std::cerr << "[MpegTsEncoder] avformat_alloc_output_context2 failed" << std::endl;
      return false;
    }

    // Immediate-emission muxer behavior (ported from runtime).
    format_ctx->max_delay = 0;
    format_ctx->max_interleave_delta = 0;
    av_dict_set(&muxer_opts, "max_delay", "0", 0);
    av_dict_set(&muxer_opts, "muxrate", "10000000", 0);
    format_ctx->flags |= AVFMT_FLAG_FLUSH_PACKETS;
    format_ctx->flush_packets = 1;

    av_opt_set(format_ctx->priv_data, "muxdelay", "0", 0);
    av_opt_set(format_ctx->priv_data, "pcr_period", "20", 0);

    // --- Custom AVIO (ported verbatim). Small cluster: 7 TS packets. ---
    const size_t buffer_size = 188 * 7;
    uint8_t* avio_buf = static_cast<uint8_t*>(av_malloc(buffer_size));
    if (!avio_buf) {
      std::cerr << "[MpegTsEncoder] Failed to allocate AVIO buffer" << std::endl;
      return false;
    }
    custom_avio_ctx = avio_alloc_context(
        avio_buf, buffer_size, 1, this, nullptr, &Impl::AVIOWriteThunk, nullptr);
    if (!custom_avio_ctx) {
      std::cerr << "[MpegTsEncoder] Failed to allocate AVIO context" << std::endl;
      av_free(avio_buf);
      return false;
    }
    custom_avio_ctx->seekable = 0;
    format_ctx->pb = custom_avio_ctx;
    format_ctx->flags |= AVFMT_FLAG_CUSTOM_IO;

    // --- Video stream + codec ctx ---
    video_stream = avformat_new_stream(format_ctx, vcodec);
    if (!video_stream) {
      std::cerr << "[MpegTsEncoder] Failed to create video stream" << std::endl;
      return false;
    }
    video_stream->id = format_ctx->nb_streams - 1;

    video_codec_ctx = avcodec_alloc_context3(vcodec);
    if (!video_codec_ctx) {
      std::cerr << "[MpegTsEncoder] Failed to alloc video codec ctx" << std::endl;
      return false;
    }
    video_codec_ctx->codec_id = vcodec->id;
    video_codec_ctx->codec_type = AVMEDIA_TYPE_VIDEO;
    video_codec_ctx->pix_fmt = AV_PIX_FMT_YUV420P;
    video_codec_ctx->width = cfg.video_width;
    video_codec_ctx->height = cfg.video_height;
    video_codec_ctx->bit_rate = cfg.video_bitrate_bps;
    // GOP ~2 seconds at channel fps.
    const double fps_approx =
        static_cast<double>(cfg.video_fps_num) / cfg.video_fps_den;
    video_codec_ctx->gop_size = std::max(1, static_cast<int>(2.0 * fps_approx + 0.5));
    video_codec_ctx->max_b_frames = 0;
    video_codec_ctx->time_base = AVRational{cfg.video_fps_den, cfg.video_fps_num};
    video_codec_ctx->framerate = AVRational{cfg.video_fps_num, cfg.video_fps_den};
    video_codec_ctx->rc_max_rate = cfg.video_bitrate_bps;
    video_codec_ctx->rc_buffer_size = cfg.video_bitrate_bps / 4;
    video_codec_ctx->flags |= AV_CODEC_FLAG_LOW_DELAY | AV_CODEC_FLAG_GLOBAL_HEADER;
    video_codec_ctx->delay = 0;

    video_stream->time_base = AVRational{1, 90000};

    {
      AVDictionary* opts = nullptr;
      av_dict_set(&opts, "preset", "ultrafast", 0);
      av_dict_set(&opts, "tune", "zerolatency", 0);
      av_dict_set(&opts, "x264-params", "bframes=0:nal-hrd=vbr:vbv-init=0.9", 0);
      ret = avcodec_open2(video_codec_ctx, vcodec, &opts);
      av_dict_free(&opts);
      if (ret < 0) {
        char errbuf[AV_ERROR_MAX_STRING_SIZE];
        av_strerror(ret, errbuf, AV_ERROR_MAX_STRING_SIZE);
        std::cerr << "[MpegTsEncoder] avcodec_open2 (video) failed: " << errbuf << std::endl;
        return false;
      }
      codec_opened = true;
    }
    ret = avcodec_parameters_from_context(video_stream->codecpar, video_codec_ctx);
    if (ret < 0) {
      std::cerr << "[MpegTsEncoder] parameters_from_context (video) failed" << std::endl;
      return false;
    }

    // --- Audio stream + codec ctx ---
    audio_stream = avformat_new_stream(format_ctx, acodec);
    if (!audio_stream) {
      std::cerr << "[MpegTsEncoder] Failed to create audio stream" << std::endl;
      return false;
    }
    audio_stream->id = format_ctx->nb_streams - 1;

    audio_codec_ctx = avcodec_alloc_context3(acodec);
    if (!audio_codec_ctx) {
      std::cerr << "[MpegTsEncoder] Failed to alloc audio codec ctx" << std::endl;
      return false;
    }
    audio_codec_ctx->codec_id = acodec->id;
    audio_codec_ctx->codec_type = AVMEDIA_TYPE_AUDIO;
    // Choose a format the encoder supports (native AAC = FLTP).
    audio_codec_ctx->sample_fmt = AV_SAMPLE_FMT_FLTP;
    if (acodec->sample_fmts) audio_codec_ctx->sample_fmt = acodec->sample_fmts[0];
    audio_codec_ctx->sample_rate = cfg.audio_sample_rate;
    audio_codec_ctx->bit_rate = cfg.audio_bitrate_bps;
    {
      uint64_t mask = (cfg.audio_channels == 1) ? AV_CH_LAYOUT_MONO
                                                : AV_CH_LAYOUT_STEREO;
      ret = av_channel_layout_from_mask(&audio_codec_ctx->ch_layout, mask);
      if (ret < 0) {
        av_channel_layout_default(&audio_codec_ctx->ch_layout, cfg.audio_channels);
      }
    }
    audio_codec_ctx->time_base = AVRational{1, cfg.audio_sample_rate};
    audio_stream->time_base = audio_codec_ctx->time_base;
    audio_codec_ctx->flags |= AV_CODEC_FLAG_GLOBAL_HEADER;

    ret = avcodec_open2(audio_codec_ctx, acodec, nullptr);
    if (ret < 0) {
      char errbuf[AV_ERROR_MAX_STRING_SIZE];
      av_strerror(ret, errbuf, AV_ERROR_MAX_STRING_SIZE);
      std::cerr << "[MpegTsEncoder] avcodec_open2 (audio) failed: " << errbuf << std::endl;
      return false;
    }
    ret = avcodec_parameters_from_context(audio_stream->codecpar, audio_codec_ctx);
    if (ret < 0) {
      std::cerr << "[MpegTsEncoder] parameters_from_context (audio) failed" << std::endl;
      return false;
    }
    audio_stream->codecpar->codec_tag = 0;

    // --- Frames + packet ---
    video_frame = av_frame_alloc();
    audio_frame = av_frame_alloc();
    packet = av_packet_alloc();
    if (!video_frame || !audio_frame || !packet) {
      std::cerr << "[MpegTsEncoder] av_frame_alloc / av_packet_alloc failed" << std::endl;
      return false;
    }
    video_frame->format = AV_PIX_FMT_YUV420P;
    video_frame->width = cfg.video_width;
    video_frame->height = cfg.video_height;
    ret = av_frame_get_buffer(video_frame, 32);
    if (ret < 0) {
      std::cerr << "[MpegTsEncoder] video av_frame_get_buffer failed" << std::endl;
      return false;
    }

    // --- Write header ---
    ret = avformat_write_header(format_ctx, &muxer_opts);
    if (ret < 0) {
      char errbuf[AV_ERROR_MAX_STRING_SIZE];
      av_strerror(ret, errbuf, AV_ERROR_MAX_STRING_SIZE);
      std::cerr << "[MpegTsEncoder] avformat_write_header failed: " << errbuf << std::endl;
      return false;
    }
    if (muxer_opts) {
      av_dict_free(&muxer_opts);
      muxer_opts = nullptr;
    }
    header_written = true;

    // --- Internal interleaver (startup holdoff on) ---
    interleaver = std::make_unique<MuxInterleaver>(
        [this](AVPacket* pkt, int64_t /*dts_90k*/) { WriteMuxPacket(pkt); });
    interleaver->SetStartupHoldoff(true);

    initialized = true;
    return true;
  }

  // ----- EncodeVideo -----
  bool EncodeVideo(const VideoFrame& frame) {
    if (!initialized || !header_written) return false;

    // Channel-canonical input: data = Y (w*h) + U (w/2*h/2) + V (w/2*h/2).
    const int w = cfg.video_width;
    const int h = cfg.video_height;
    const size_t y_size = static_cast<size_t>(w) * static_cast<size_t>(h);
    const size_t uv_size = static_cast<size_t>(w / 2) * static_cast<size_t>(h / 2);
    const size_t expected = y_size + 2 * uv_size;
    if (frame.data.size() != expected) {
      std::cerr << "[MpegTsEncoder] EncodeVideo: data size " << frame.data.size()
                << " != expected " << expected << std::endl;
      return false;
    }

    int wr = av_frame_make_writable(video_frame);
    if (wr < 0) {
      std::cerr << "[MpegTsEncoder] av_frame_make_writable failed (video)" << std::endl;
      return false;
    }

    // Copy Y/U/V planes row-by-row respecting linesize.
    const uint8_t* y_src = frame.data.data();
    for (int row = 0; row < h; ++row) {
      std::memcpy(video_frame->data[0] + row * video_frame->linesize[0],
                  y_src + row * w, static_cast<size_t>(w));
    }
    const int uv_w = w / 2;
    const int uv_h = h / 2;
    const uint8_t* u_src = frame.data.data() + y_size;
    for (int row = 0; row < uv_h; ++row) {
      std::memcpy(video_frame->data[1] + row * video_frame->linesize[1],
                  u_src + row * uv_w, static_cast<size_t>(uv_w));
    }
    const uint8_t* v_src = frame.data.data() + y_size + uv_size;
    for (int row = 0; row < uv_h; ++row) {
      std::memcpy(video_frame->data[2] + row * video_frame->linesize[2],
                  v_src + row * uv_w, static_cast<size_t>(uv_w));
    }
    video_frame->format = AV_PIX_FMT_YUV420P;

    // PTS: us -> 90k -> codec timebase. Enforce strictly increasing.
    AVRational tb90k{1, 90000};
    int64_t pts_90k = frame.pts_us_relative * 90000 / 1'000'000;
    int64_t pts_codec =
        av_rescale_q(pts_90k, tb90k, video_codec_ctx->time_base);
    if (last_video_input_pts != AV_NOPTS_VALUE && pts_codec <= last_video_input_pts) {
      pts_codec = last_video_input_pts + 1;
    }
    last_video_input_pts = pts_codec;
    video_frame->pts = pts_codec;
    video_frame->metadata = nullptr;
    video_frame->opaque = nullptr;

    // Force first frame to IDR.
    if (!first_frame_encoded) {
      video_frame->pict_type = AV_PICTURE_TYPE_I;
      first_frame_encoded = true;
    } else {
      video_frame->pict_type = AV_PICTURE_TYPE_NONE;
    }

    int send_ret = avcodec_send_frame(video_codec_ctx, video_frame);
    if (send_ret < 0 && send_ret != AVERROR(EAGAIN)) {
      char errbuf[AV_ERROR_MAX_STRING_SIZE];
      av_strerror(send_ret, errbuf, AV_ERROR_MAX_STRING_SIZE);
      std::cerr << "[MpegTsEncoder] send_frame (video) error: " << errbuf << std::endl;
      return false;
    }

    constexpr int kMaxPacketsPerFrame = 10;
    int n = 0;
    while (n < kMaxPacketsPerFrame) {
      int recv_ret = avcodec_receive_packet(video_codec_ctx, packet);
      if (recv_ret == AVERROR(EAGAIN) || recv_ret == AVERROR_EOF) break;
      if (recv_ret < 0) {
        char errbuf[AV_ERROR_MAX_STRING_SIZE];
        av_strerror(recv_ret, errbuf, AV_ERROR_MAX_STRING_SIZE);
        std::cerr << "[MpegTsEncoder] receive_packet (video) error: " << errbuf << std::endl;
        return false;
      }
      ++n;

      // INV-AIR-IDR-BEFORE-OUTPUT: gate non-keyframes until first IDR emitted.
      if (!first_keyframe_emitted) {
        if (packet->flags & AV_PKT_FLAG_KEY) {
          first_keyframe_emitted = true;
        } else {
          av_packet_unref(packet);
          continue;
        }
      }

      packet->stream_index = video_stream->index;
      av_packet_rescale_ts(packet, video_codec_ctx->time_base,
                           video_stream->time_base);
      EnforceMonotonicDts();
      EmitPacket();
    }

    // INV-MUX-CYCLE-FLUSH: flush interleaver at cycle boundary.
    if (interleaver) interleaver->Flush();

    return true;
  }

  // ----- EncodeAudio -----
  bool EncodeAudio(const AudioBlock& block) {
    if (!initialized || !header_written) return false;
    if (!audio_codec_ctx || !audio_stream || !audio_frame || !packet) return false;

    const int encoder_sample_rate = audio_codec_ctx->sample_rate;
    const int encoder_channels = audio_codec_ctx->ch_layout.nb_channels;
    if (encoder_sample_rate != cfg.audio_sample_rate ||
        encoder_channels != cfg.audio_channels) {
      std::cerr << "[MpegTsEncoder] Audio encoder mis-configured" << std::endl;
      return false;
    }
    if (block.nb_samples <= 0) return true;  // nothing to do
    if (static_cast<int>(block.data.size()) != block.nb_samples * encoder_channels) {
      std::cerr << "[MpegTsEncoder] EncodeAudio: data.size mismatch" << std::endl;
      return false;
    }

    const int frame_size = audio_codec_ctx->frame_size > 0
                               ? audio_codec_ctx->frame_size
                               : 1024;

    // Combine remainder + new samples.
    std::vector<int16_t> combined;
    combined.reserve((audio_remainder_samples + block.nb_samples) * encoder_channels);
    if (audio_remainder_samples > 0) {
      combined.insert(combined.end(), audio_remainder.begin(),
                      audio_remainder.begin() +
                          audio_remainder_samples * encoder_channels);
      audio_remainder_samples = 0;
    }
    combined.insert(combined.end(), block.data.begin(), block.data.end());

    int total_samples = static_cast<int>(combined.size()) / encoder_channels;
    const int16_t* samples_ptr = combined.data();
    int samples_remaining = total_samples;

    AVRational tb90k{1, 90000};
    AVRational tb_audio = audio_codec_ctx->time_base;

    while (samples_remaining >= frame_size) {
      const int this_frame = frame_size;

      // INV-AUDIO-SAMPLE-CLOCK: PTS from counter.
      int64_t pts_90k =
          (audio_encode_sample_counter * 90000) / encoder_sample_rate;
      audio_frame->pts = av_rescale_q(pts_90k, tb90k, tb_audio);

      if (!audio_frame->buf[0]) {
        audio_frame->format = audio_codec_ctx->sample_fmt;
        audio_frame->sample_rate = encoder_sample_rate;
        int cret =
            av_channel_layout_copy(&audio_frame->ch_layout, &audio_codec_ctx->ch_layout);
        if (cret < 0) {
          std::cerr << "[MpegTsEncoder] av_channel_layout_copy failed" << std::endl;
          return false;
        }
        audio_frame->nb_samples = this_frame;
        int gret = av_frame_get_buffer(audio_frame, 0);
        if (gret < 0) {
          std::cerr << "[MpegTsEncoder] audio av_frame_get_buffer failed" << std::endl;
          return false;
        }
      } else {
        int mret = av_frame_make_writable(audio_frame);
        if (mret < 0) {
          std::cerr << "[MpegTsEncoder] av_frame_make_writable failed (audio)" << std::endl;
          return false;
        }
      }

      // Copy/convert into encoder format.
      if (audio_codec_ctx->sample_fmt == AV_SAMPLE_FMT_S16) {
        const size_t data_size =
            static_cast<size_t>(this_frame) *
            static_cast<size_t>(encoder_channels) * sizeof(int16_t);
        std::memcpy(audio_frame->data[0], samples_ptr, data_size);
      } else if (audio_codec_ctx->sample_fmt == AV_SAMPLE_FMT_FLTP) {
        for (int c = 0; c < encoder_channels; ++c) {
          float* dst = reinterpret_cast<float*>(audio_frame->data[c]);
          for (int i = 0; i < this_frame; ++i) {
            int16_t s = samples_ptr[i * encoder_channels + c];
            dst[i] = static_cast<float>(s) / 32768.0f;
          }
        }
      } else if (audio_codec_ctx->sample_fmt == AV_SAMPLE_FMT_FLT) {
        float* dst = reinterpret_cast<float*>(audio_frame->data[0]);
        for (int i = 0; i < this_frame * encoder_channels; ++i) {
          dst[i] = static_cast<float>(samples_ptr[i]) / 32768.0f;
        }
      } else {
        std::cerr << "[MpegTsEncoder] Unsupported audio sample_fmt: "
                  << audio_codec_ctx->sample_fmt << std::endl;
        return false;
      }

      int send_ret = avcodec_send_frame(audio_codec_ctx, audio_frame);
      if (send_ret < 0 && send_ret != AVERROR(EAGAIN)) {
        char errbuf[AV_ERROR_MAX_STRING_SIZE];
        av_strerror(send_ret, errbuf, AV_ERROR_MAX_STRING_SIZE);
        std::cerr << "[MpegTsEncoder] send_frame (audio) error: " << errbuf << std::endl;
        return false;
      }

      DrainAudioPackets();

      samples_ptr += this_frame * encoder_channels;
      samples_remaining -= this_frame;
      audio_encode_sample_counter += this_frame;
    }

    // Stash remainder for next call.
    if (samples_remaining > 0) {
      audio_remainder.resize(samples_remaining * encoder_channels);
      std::memcpy(audio_remainder.data(), samples_ptr,
                  static_cast<size_t>(samples_remaining) *
                      static_cast<size_t>(encoder_channels) * sizeof(int16_t));
      audio_remainder_samples = samples_remaining;
    }

    return true;
  }

  void DrainAudioPackets() {
    while (true) {
      int ret = avcodec_receive_packet(audio_codec_ctx, packet);
      if (ret == AVERROR(EAGAIN) || ret == AVERROR_EOF) break;
      if (ret < 0) {
        char errbuf[AV_ERROR_MAX_STRING_SIZE];
        av_strerror(ret, errbuf, AV_ERROR_MAX_STRING_SIZE);
        std::cerr << "[MpegTsEncoder] receive_packet (audio) error: " << errbuf << std::endl;
        return;
      }
      packet->stream_index = audio_stream->index;
      av_packet_rescale_ts(packet, audio_codec_ctx->time_base,
                           audio_stream->time_base);
      // INV-AAC-PRIMING-DROP: AAC emits a negative-DTS priming packet; drop it.
      if (packet->dts != AV_NOPTS_VALUE && packet->dts < 0) {
        av_packet_unref(packet);
        continue;
      }
      EnforceMonotonicDts();
      EmitPacket();
    }
  }

  // ----- Flush -----
  void Flush() {
    if (!initialized) return;

    // Drain video encoder.
    if (video_codec_ctx && codec_opened) {
      avcodec_send_frame(video_codec_ctx, nullptr);
      while (true) {
        int ret = avcodec_receive_packet(video_codec_ctx, packet);
        if (ret == AVERROR(EAGAIN) || ret == AVERROR_EOF) break;
        if (ret < 0) break;
        // Honor IDR gate if somehow not yet satisfied (should not happen).
        if (!first_keyframe_emitted) {
          if (packet->flags & AV_PKT_FLAG_KEY) {
            first_keyframe_emitted = true;
          } else {
            av_packet_unref(packet);
            continue;
          }
        }
        packet->stream_index = video_stream->index;
        av_packet_rescale_ts(packet, video_codec_ctx->time_base,
                             video_stream->time_base);
        EnforceMonotonicDts();
        EmitPacket();
      }
    }

    // Drain audio encoder.
    if (audio_codec_ctx) {
      avcodec_send_frame(audio_codec_ctx, nullptr);
      DrainAudioPackets();
    }

    // DrainAll interleaver (ignore watermark, no more packets will arrive).
    if (interleaver) interleaver->DrainAll();

    // Write trailer.
    if (format_ctx && header_written) {
      av_write_trailer(format_ctx);
      if (format_ctx->pb) avio_flush(format_ctx->pb);
    }
  }

  // ----- Close -----
  void Close() {
    if (!initialized) {
      // Clean up partial state if Open() failed mid-way.
      if (muxer_opts) { av_dict_free(&muxer_opts); muxer_opts = nullptr; }
      if (video_frame) { av_frame_free(&video_frame); }
      if (audio_frame) { av_frame_free(&audio_frame); }
      if (packet) { av_packet_free(&packet); }
      if (video_codec_ctx) { avcodec_free_context(&video_codec_ctx); }
      if (audio_codec_ctx) { avcodec_free_context(&audio_codec_ctx); }
      if (custom_avio_ctx) {
        avio_context_free(&custom_avio_ctx);
        if (format_ctx) format_ctx->pb = nullptr;
      }
      if (format_ctx) { avformat_free_context(format_ctx); format_ctx = nullptr; }
      return;
    }

    // Reset interleaver first to release cloned packets.
    if (interleaver) { interleaver->Reset(); interleaver.reset(); }

    if (muxer_opts) { av_dict_free(&muxer_opts); muxer_opts = nullptr; }

    if (video_frame) { av_frame_free(&video_frame); }
    if (audio_frame) { av_frame_free(&audio_frame); }
    if (packet) { av_packet_free(&packet); }

    if (video_codec_ctx) { avcodec_free_context(&video_codec_ctx); }
    if (audio_codec_ctx) { avcodec_free_context(&audio_codec_ctx); }

    if (custom_avio_ctx) {
      avio_context_free(&custom_avio_ctx);
      custom_avio_ctx = nullptr;
      if (format_ctx) format_ctx->pb = nullptr;
    }
    if (format_ctx) {
      avformat_free_context(format_ctx);
      format_ctx = nullptr;
    }

    video_stream = nullptr;
    audio_stream = nullptr;

    header_written = false;
    codec_opened = false;
    initialized = false;
    first_frame_encoded = false;
    first_keyframe_emitted = false;
    last_video_mux_dts = AV_NOPTS_VALUE;
    last_video_mux_pts = AV_NOPTS_VALUE;
    last_audio_mux_dts = AV_NOPTS_VALUE;
    last_audio_mux_pts = AV_NOPTS_VALUE;
    last_video_input_pts = AV_NOPTS_VALUE;
    audio_remainder.clear();
    audio_remainder_samples = 0;
    audio_encode_sample_counter = 0;
  }

  ~Impl() { Close(); }
};

// ---------------------------------------------------------------------------
// Public API (thin forwarding layer).
// ---------------------------------------------------------------------------

MpegTsEncoder::MpegTsEncoder() : impl_(std::make_unique<Impl>()) {}
MpegTsEncoder::~MpegTsEncoder() { /* Impl dtor runs Close() */ }

bool MpegTsEncoder::Open(const MpegTsEncoderConfig& config,
                         BytesOutCallback bytes_out) {
  return impl_->Open(config, std::move(bytes_out));
}

bool MpegTsEncoder::EncodeVideo(const VideoFrame& frame) {
  return impl_->EncodeVideo(frame);
}

bool MpegTsEncoder::EncodeAudio(const AudioBlock& block) {
  return impl_->EncodeAudio(block);
}

void MpegTsEncoder::Flush() { impl_->Flush(); }

void MpegTsEncoder::Close() { impl_->Close(); }

bool MpegTsEncoder::IsOpen() const { return impl_->initialized; }

}  // namespace retrovue::air
