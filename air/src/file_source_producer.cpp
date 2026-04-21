// AIR vNext — FileSourceProducer implementation.

#include "file_source_producer.hpp"

extern "C" {
#include <libavcodec/avcodec.h>
#include <libavformat/avformat.h>
#include <libavutil/channel_layout.h>
#include <libavutil/opt.h>
#include <libavutil/pixfmt.h>
#include <libavutil/rational.h>
#include <libavutil/samplefmt.h>
#include <libswresample/swresample.h>
}

#include <algorithm>
#include <cstring>
#include <deque>
#include <utility>
#include <vector>

namespace retrovue::air {

struct FileSourceProducer::Impl {
  AVFormatContext* fmt = nullptr;

  // Video stream
  int v_idx = -1;
  AVCodecContext* v_ctx = nullptr;
  AVRational v_tb{0, 1};
  AVRational v_fr{0, 1};

  // Audio stream
  int a_idx = -1;
  AVCodecContext* a_ctx = nullptr;
  AVRational a_tb{0, 1};
  int a_out_rate = 0;
  int a_out_channels = 0;
  SwrContext* swr = nullptr;

  // Reusable buffers
  AVPacket* pkt = nullptr;
  AVFrame* frame = nullptr;

  // Output queues
  std::deque<SourceVideoFrame> v_out;
  std::deque<SourceAudioBlock> a_out;

  bool eof = false;
  ProducerHealth health = ProducerHealth::kHealthy;

  ~Impl() {
    if (swr) swr_free(&swr);
    if (v_ctx) avcodec_free_context(&v_ctx);
    if (a_ctx) avcodec_free_context(&a_ctx);
    if (fmt) avformat_close_input(&fmt);
    if (pkt) av_packet_free(&pkt);
    if (frame) av_frame_free(&frame);
  }
};

namespace {

// Convert and queue a decoded YUV420P video frame as a SourceVideoFrame.
void QueueVideoFrame(FileSourceProducer::Impl* impl, AVFrame* f,
                     AVRational tb) {
  if (f->format != AV_PIX_FMT_YUV420P) {
    impl->health = ProducerHealth::kFailed;
    return;
  }
  const int w = f->width;
  const int h = f->height;

  SourceVideoFrame out;
  out.width = w;
  out.height = h;
  const int64_t pts = (f->pts != AV_NOPTS_VALUE)
                          ? f->pts
                          : f->best_effort_timestamp;
  out.source_pts_us = av_rescale_q(pts, tb, AVRational{1, 1'000'000});

  // Pack Y, U, V planes contiguously. Row stride in AVFrame (linesize)
  // may exceed plane width; copy row-by-row.
  const int y_size = w * h;
  const int uv_w = w / 2;
  const int uv_h = h / 2;
  const int uv_size = uv_w * uv_h;
  out.data.resize(static_cast<size_t>(y_size + 2 * uv_size));

  uint8_t* dst_y = out.data.data();
  uint8_t* dst_u = dst_y + y_size;
  uint8_t* dst_v = dst_u + uv_size;

  for (int y = 0; y < h; ++y) {
    std::memcpy(dst_y + y * w,
                f->data[0] + y * f->linesize[0],
                static_cast<size_t>(w));
  }
  for (int y = 0; y < uv_h; ++y) {
    std::memcpy(dst_u + y * uv_w,
                f->data[1] + y * f->linesize[1],
                static_cast<size_t>(uv_w));
    std::memcpy(dst_v + y * uv_w,
                f->data[2] + y * f->linesize[2],
                static_cast<size_t>(uv_w));
  }

  impl->v_out.push_back(std::move(out));
}

// Convert and queue a decoded audio frame as a SourceAudioBlock (S16
// interleaved, source-native sample rate).
void QueueAudioFrame(FileSourceProducer::Impl* impl, AVFrame* f,
                     AVRational tb) {
  const int channels = impl->a_out_channels;
  const int in_nb = f->nb_samples;

  // Output buffer: up to in_nb + any swr internal delay samples.
  const int out_max = in_nb + swr_get_delay(impl->swr, impl->a_out_rate);
  std::vector<int16_t> interleaved(
      static_cast<size_t>(out_max) * static_cast<size_t>(channels));

  uint8_t* out_bufs[1] = {
      reinterpret_cast<uint8_t*>(interleaved.data())};
  const uint8_t** in_bufs =
      const_cast<const uint8_t**>(f->data);

  const int ret = swr_convert(impl->swr, out_bufs, out_max, in_bufs, in_nb);
  if (ret < 0) {
    impl->health = ProducerHealth::kFailed;
    return;
  }

  SourceAudioBlock blk;
  blk.sample_rate = impl->a_out_rate;
  blk.channels = channels;
  blk.nb_samples = ret;
  const int64_t pts = (f->pts != AV_NOPTS_VALUE)
                          ? f->pts
                          : f->best_effort_timestamp;
  blk.source_pts_us = av_rescale_q(pts, tb, AVRational{1, 1'000'000});
  interleaved.resize(static_cast<size_t>(ret) *
                     static_cast<size_t>(channels));
  blk.data = std::move(interleaved);
  impl->a_out.push_back(std::move(blk));
}

// Drain any buffered frames from a decoder after EOF.
void DrainDecoder(FileSourceProducer::Impl* impl, AVCodecContext* cctx,
                  AVRational tb, bool is_video) {
  avcodec_send_packet(cctx, nullptr);
  while (true) {
    const int rf = avcodec_receive_frame(cctx, impl->frame);
    if (rf == AVERROR(EAGAIN) || rf == AVERROR_EOF) break;
    if (rf < 0) {
      impl->eof = true;
      break;
    }
    if (is_video) QueueVideoFrame(impl, impl->frame, tb);
    else QueueAudioFrame(impl, impl->frame, tb);
    av_frame_unref(impl->frame);
  }
}

// Pump: read one packet, decode, queue outputs. Returns true if a packet
// was read (may not have produced an output yet). False on EOF.
bool Pump(FileSourceProducer::Impl* impl) {
  if (impl->eof) return false;

  const int ret = av_read_frame(impl->fmt, impl->pkt);
  if (ret < 0) {
    // EOF or unrecoverable error. Drain decoders and mark EOF.
    if (impl->v_ctx) DrainDecoder(impl, impl->v_ctx, impl->v_tb, true);
    if (impl->a_ctx) DrainDecoder(impl, impl->a_ctx, impl->a_tb, false);
    impl->eof = true;
    return false;
  }

  AVCodecContext* cctx = nullptr;
  AVRational tb{};
  bool is_video = false;
  if (impl->pkt->stream_index == impl->v_idx) {
    cctx = impl->v_ctx;
    tb = impl->v_tb;
    is_video = true;
  } else if (impl->pkt->stream_index == impl->a_idx) {
    cctx = impl->a_ctx;
    tb = impl->a_tb;
    is_video = false;
  }

  if (cctx) {
    const int rv = avcodec_send_packet(cctx, impl->pkt);
    if (rv == 0 || rv == AVERROR(EAGAIN)) {
      while (true) {
        const int rf = avcodec_receive_frame(cctx, impl->frame);
        if (rf == AVERROR(EAGAIN) || rf == AVERROR_EOF) break;
        if (rf < 0) {
          impl->eof = true;
          break;
        }
        if (is_video) QueueVideoFrame(impl, impl->frame, tb);
        else QueueAudioFrame(impl, impl->frame, tb);
        av_frame_unref(impl->frame);
      }
    }
  }

  av_packet_unref(impl->pkt);
  return true;
}

}  // namespace

FileSourceProducer::FileSourceProducer(Config config)
    : impl_(std::make_unique<Impl>()), config_(std::move(config)) {}

FileSourceProducer::~FileSourceProducer() = default;

bool FileSourceProducer::Prepare() {
  if (lifecycle_ != ProducerLifecycle::kConstructed) return false;

  if (avformat_open_input(&impl_->fmt, config_.file_path.c_str(),
                          nullptr, nullptr) < 0) {
    impl_->health = ProducerHealth::kFailed;
    return false;
  }
  if (avformat_find_stream_info(impl_->fmt, nullptr) < 0) {
    impl_->health = ProducerHealth::kFailed;
    return false;
  }

  // Locate first video and audio streams.
  for (unsigned i = 0; i < impl_->fmt->nb_streams; ++i) {
    AVCodecParameters* cp = impl_->fmt->streams[i]->codecpar;
    if (impl_->v_idx < 0 && cp->codec_type == AVMEDIA_TYPE_VIDEO) {
      impl_->v_idx = static_cast<int>(i);
    } else if (impl_->a_idx < 0 && cp->codec_type == AVMEDIA_TYPE_AUDIO) {
      impl_->a_idx = static_cast<int>(i);
    }
  }

  // Open video decoder.
  if (impl_->v_idx >= 0) {
    AVStream* st = impl_->fmt->streams[impl_->v_idx];
    const AVCodec* codec = avcodec_find_decoder(st->codecpar->codec_id);
    if (!codec) {
      impl_->health = ProducerHealth::kFailed;
      return false;
    }
    impl_->v_ctx = avcodec_alloc_context3(codec);
    if (!impl_->v_ctx) {
      impl_->health = ProducerHealth::kFailed;
      return false;
    }
    avcodec_parameters_to_context(impl_->v_ctx, st->codecpar);
    if (avcodec_open2(impl_->v_ctx, codec, nullptr) < 0) {
      impl_->health = ProducerHealth::kFailed;
      return false;
    }
    impl_->v_tb = st->time_base;
    impl_->v_fr =
        st->avg_frame_rate.num != 0 ? st->avg_frame_rate : st->r_frame_rate;

    if (config_.require_yuv420p &&
        st->codecpar->format != AV_PIX_FMT_YUV420P &&
        impl_->v_ctx->pix_fmt != AV_PIX_FMT_YUV420P) {
      // Pixel format may be set lazily after first decode; accept and let
      // QueueVideoFrame reject the first frame if it's non-YUV420P.
    }
  }

  // Open audio decoder and swresample.
  if (impl_->a_idx >= 0) {
    AVStream* st = impl_->fmt->streams[impl_->a_idx];
    const AVCodec* codec = avcodec_find_decoder(st->codecpar->codec_id);
    if (!codec) {
      impl_->health = ProducerHealth::kFailed;
      return false;
    }
    impl_->a_ctx = avcodec_alloc_context3(codec);
    if (!impl_->a_ctx) {
      impl_->health = ProducerHealth::kFailed;
      return false;
    }
    avcodec_parameters_to_context(impl_->a_ctx, st->codecpar);
    if (avcodec_open2(impl_->a_ctx, codec, nullptr) < 0) {
      impl_->health = ProducerHealth::kFailed;
      return false;
    }
    impl_->a_tb = st->time_base;
    impl_->a_out_rate = impl_->a_ctx->sample_rate;
    impl_->a_out_channels = impl_->a_ctx->ch_layout.nb_channels;

    // swresample: pass through at source rate, convert to S16 interleaved.
    impl_->swr = swr_alloc();
    av_opt_set_chlayout(impl_->swr, "in_chlayout",
                        &impl_->a_ctx->ch_layout, 0);
    av_opt_set_int(impl_->swr, "in_sample_rate",
                   impl_->a_ctx->sample_rate, 0);
    av_opt_set_sample_fmt(impl_->swr, "in_sample_fmt",
                          impl_->a_ctx->sample_fmt, 0);
    av_opt_set_chlayout(impl_->swr, "out_chlayout",
                        &impl_->a_ctx->ch_layout, 0);
    av_opt_set_int(impl_->swr, "out_sample_rate", impl_->a_out_rate, 0);
    av_opt_set_sample_fmt(impl_->swr, "out_sample_fmt",
                          AV_SAMPLE_FMT_S16, 0);
    if (swr_init(impl_->swr) < 0) {
      impl_->health = ProducerHealth::kFailed;
      return false;
    }
  }

  impl_->pkt = av_packet_alloc();
  impl_->frame = av_frame_alloc();
  if (!impl_->pkt || !impl_->frame) {
    impl_->health = ProducerHealth::kFailed;
    return false;
  }

  lifecycle_ = ProducerLifecycle::kPrepared;
  return true;
}

bool FileSourceProducer::Activate() {
  if (lifecycle_ != ProducerLifecycle::kPrepared) return false;
  lifecycle_ = ProducerLifecycle::kActivated;
  return true;
}

void FileSourceProducer::Retire() {
  lifecycle_ = ProducerLifecycle::kRetired;
}

bool FileSourceProducer::SeekTo(int64_t offset_ms) {
  if (lifecycle_ != ProducerLifecycle::kPrepared &&
      lifecycle_ != ProducerLifecycle::kActivated) {
    return false;
  }
  if (impl_->v_idx < 0 || !impl_->fmt) return false;

  // Convert ms to stream-timebase PTS on the video stream:
  //   pts = offset_s / tb = offset_ms * tb_den / (tb_num * 1000)
  const int64_t seek_pts = av_rescale(
      offset_ms, impl_->v_tb.den, impl_->v_tb.num * int64_t{1000});

  // AVSEEK_FLAG_BACKWARD: land on nearest keyframe <= target. Low-level
  // primitive only; frame-accurate entry requires SeekFrameAccurate.
  const int ret = av_seek_frame(impl_->fmt, impl_->v_idx, seek_pts,
                                AVSEEK_FLAG_BACKWARD);
  if (ret < 0) return false;

  if (impl_->v_ctx) avcodec_flush_buffers(impl_->v_ctx);
  if (impl_->a_ctx) avcodec_flush_buffers(impl_->a_ctx);

  impl_->v_out.clear();
  impl_->a_out.clear();
  impl_->eof = false;
  return true;
}

bool FileSourceProducer::SeekFrameAccurate(int64_t offset_ms) {
  if (!SeekTo(offset_ms)) return false;

  const int64_t target_us = offset_ms * int64_t{1000};

  // Forward decode-and-discard on video: pump until v_out has a frame;
  // if its source_pts_us is before the target, discard and keep pumping.
  // Exit when the front frame is at-or-after target (success) or the
  // stream EOFs before reaching the target (failure). EOF-before-target
  // returns false per C1.H1a so callers can distinguish "positioned"
  // from "cannot position"; activating a seam on a non-positioned
  // successor is a silent-failure path downstream.
  while (true) {
    while (impl_->v_out.empty() && !impl_->eof) {
      if (!Pump(impl_.get())) break;
    }
    if (impl_->v_out.empty()) return false;
    if (impl_->v_out.front().source_pts_us >= target_us) break;
    impl_->v_out.pop_front();
  }

  // Audio: discard blocks whose END PTS is strictly before the target,
  // so the block that straddles the target (if any) is retained. Up to
  // one block of sample-level slop is accepted; video-frame precision
  // is the vault contract.
  while (true) {
    while (impl_->a_out.empty() && !impl_->eof) {
      if (!Pump(impl_.get())) break;
    }
    if (impl_->a_out.empty()) break;
    const auto& blk = impl_->a_out.front();
    const int64_t blk_end_us =
        blk.source_pts_us +
        (static_cast<int64_t>(blk.nb_samples) * int64_t{1'000'000}) /
            std::max(blk.sample_rate, 1);
    if (blk_end_us >= target_us) break;
    impl_->a_out.pop_front();
  }

  return true;
}

std::optional<SourceVideoFrame> FileSourceProducer::PullVideo() {
  if (lifecycle_ != ProducerLifecycle::kActivated) return std::nullopt;
  while (impl_->v_out.empty() && !impl_->eof) {
    if (!Pump(impl_.get())) break;
    if (impl_->health != ProducerHealth::kHealthy) return std::nullopt;
  }
  if (impl_->v_out.empty()) return std::nullopt;
  SourceVideoFrame f = std::move(impl_->v_out.front());
  impl_->v_out.pop_front();
  return f;
}

std::optional<SourceAudioBlock> FileSourceProducer::PullAudio() {
  if (lifecycle_ != ProducerLifecycle::kActivated) return std::nullopt;
  while (impl_->a_out.empty() && !impl_->eof) {
    if (!Pump(impl_.get())) break;
    if (impl_->health != ProducerHealth::kHealthy) return std::nullopt;
  }
  if (impl_->a_out.empty()) return std::nullopt;
  SourceAudioBlock b = std::move(impl_->a_out.front());
  impl_->a_out.pop_front();
  return b;
}

ProducerHealth FileSourceProducer::Health() const { return impl_->health; }
ProducerLifecycle FileSourceProducer::Lifecycle() const { return lifecycle_; }

bool FileSourceProducer::HasVideoStream() const { return impl_->v_idx >= 0; }
bool FileSourceProducer::HasAudioStream() const { return impl_->a_idx >= 0; }

int FileSourceProducer::VideoWidth() const {
  return impl_->v_ctx ? impl_->v_ctx->width : 0;
}
int FileSourceProducer::VideoHeight() const {
  return impl_->v_ctx ? impl_->v_ctx->height : 0;
}
Rational FileSourceProducer::VideoFrameRate() const {
  return {impl_->v_fr.num, impl_->v_fr.den};
}
int FileSourceProducer::AudioSampleRate() const { return impl_->a_out_rate; }
int FileSourceProducer::AudioChannels() const {
  return impl_->a_out_channels;
}

}  // namespace retrovue::air
