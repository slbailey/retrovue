// AIR vNext — AirSession implementation.
//
// Orchestrates the three-phase startup (AttachOutput → AssignContent →
// OpenAir). Each phase is distinct and guarded by preconditions on the
// previous phases having succeeded. Owned member groups are explicitly
// separated (sink group / content group / on-air group) so a future
// device-centric retune can swap content without touching the sink.
//
// Threading:
//   - AttachOutput/AssignContent/OpenAir/Close run on the calling thread
//     (today the gRPC handler thread). They are non-blocking — no encode
//     work happens inline.
//   - EncodeLoop runs on encode_thread_, started by OpenAir() and joined
//     by Close().

#include "air_session.hpp"

#include <unistd.h>

#include <utility>

#include "egress_pacer.hpp"
#include "file_source_producer.hpp"
#include "mpeg_ts_encoder.hpp"
#include "socket_emitter.hpp"
#include "standard_normalizer.hpp"

namespace retrovue::air {

AirSession::AirSession() = default;

AirSession::~AirSession() { Close(); }

bool AirSession::AttachOutput(int fd) {
  // Preconditions: no output attached, fd is valid.
  if (emitter_ != nullptr || owned_fd_ >= 0) return false;
  if (fd < 0) return false;

  owned_fd_ = fd;
  emitter_ = std::make_unique<SocketEmitter>(fd);
  return true;
}

bool AirSession::AssignContent(const std::string& input_path,
                               const ChannelCanonical& canonical) {
  // Preconditions: output attached, content not yet assigned.
  if (emitter_ == nullptr) return false;
  if (source_ != nullptr) return false;
  if (!canonical.IsValid()) return false;

  canonical_ = canonical;

  // Channel audio block: ~ one video-frame-period of samples at the
  // channel audio rate. For 30000/1001 video at 48kHz audio, this is
  // ~1601 samples. Hardcoded for now (matches existing tests).
  audio_samples_per_block_ = 1601;

  // Build FileSourceProducer.
  auto source = std::make_unique<FileSourceProducer>(
      FileSourceProducer::Config{.file_path = input_path});
  if (!source->Prepare()) return false;
  if (!source->Activate()) return false;

  // Build StandardNormalizer, matching the pattern from encoder_smoke_test.
  auto normalizer = std::make_unique<StandardNormalizer>(
      canonical_, source->VideoFrameRate(), source->VideoWidth(),
      source->VideoHeight(), source->AudioSampleRate(), source.get(),
      ChannelOrigin{.source_pts_anchor_us = 0,
                    .channel_pts_anchor_us = 0},
      audio_samples_per_block_);

  // Build + open MpegTsEncoder with a callback that writes to emitter_.
  auto encoder = std::make_unique<MpegTsEncoder>();
  MpegTsEncoderConfig cfg{
      .video_width = canonical_.video.width,
      .video_height = canonical_.video.height,
      .video_fps_num = static_cast<int>(canonical_.video.frame_rate.num),
      .video_fps_den = static_cast<int>(canonical_.video.frame_rate.den),
      .video_bitrate_bps = 4'000'000,
      .audio_sample_rate = canonical_.audio.sample_rate,
      .audio_channels = canonical_.audio.channels,
      .audio_bitrate_bps = 192'000,
  };
  SocketEmitter* emitter_ptr = emitter_.get();
  if (!encoder->Open(cfg, [emitter_ptr](const uint8_t* buf, int n) {
        return emitter_ptr->Write(buf, n);
      })) {
    return false;
  }

  // Commit. Everything constructed successfully; install in member state.
  source_ = std::move(source);
  normalizer_ = std::move(normalizer);
  encoder_ = std::move(encoder);
  return true;
}

bool AirSession::OpenAir() {
  // Preconditions: output + content attached, not already on air.
  if (emitter_ == nullptr) return false;
  if (source_ == nullptr || normalizer_ == nullptr || encoder_ == nullptr) {
    return false;
  }
  if (encode_thread_.joinable()) return false;

  pacer_ = std::make_unique<EgressPacer>();
  stopping_.store(false);
  encode_thread_ = std::thread([this]() { EncodeLoop(); });
  return true;
}

void AirSession::EncodeLoop() {
  // Mirrors the pattern in main.cpp (pre-vNext gRPC binary).
  while (!stopping_.load()) {
    auto vf = normalizer_->PullVideo();
    if (!vf.has_value()) break;  // natural EOF
    pacer_->WaitFor(vf->pts_us_relative);
    if (!encoder_->EncodeVideo(*vf)) break;
    frames_encoded_.fetch_add(1);
    auto ab = normalizer_->PullAudio();
    if (ab.has_value()) encoder_->EncodeAudio(*ab);
  }
  // Drain a few extra audio blocks so the interleaver has enough audio
  // to cover the video span on final flush.
  for (int extra = 0; extra < 10; ++extra) {
    auto ab = normalizer_->PullAudio();
    if (!ab.has_value()) break;
    encoder_->EncodeAudio(*ab);
  }
  if (encoder_) encoder_->Flush();
}

void AirSession::Close() {
  stopping_.store(true);
  if (encode_thread_.joinable()) {
    encode_thread_.join();
  }
  if (encoder_) {
    encoder_->Close();
  }
  if (owned_fd_ >= 0) {
    ::close(owned_fd_);
    owned_fd_ = -1;
  }
  // Retire source after the encode thread has stopped pulling from it.
  if (source_) {
    source_->Retire();
  }
  encoder_.reset();
  pacer_.reset();
  normalizer_.reset();
  source_.reset();
  emitter_.reset();
  frames_encoded_.store(0);
  stopping_.store(false);
}

int64_t AirSession::BytesWritten() const {
  return emitter_ ? emitter_->BytesWrittenTotal() : 0;
}

int64_t AirSession::BytesDropped() const {
  return emitter_ ? emitter_->BytesDroppedTotal() : 0;
}

int64_t AirSession::PacerSleepMs() const {
  return pacer_ ? (pacer_->TotalSleepUs() / 1000) : 0;
}

int64_t AirSession::PacerLateReleases() const {
  return pacer_ ? pacer_->LateReleases() : 0;
}

}  // namespace retrovue::air
