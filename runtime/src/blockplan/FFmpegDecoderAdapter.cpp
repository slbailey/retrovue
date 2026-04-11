// Repository: Retrovue-playout
// Component: FFmpegDecoderAdapter
// Copyright (c) 2025 RetroVue

#include "retrovue/blockplan/FFmpegDecoderAdapter.hpp"

namespace retrovue::blockplan {

FFmpegDecoderAdapter::FFmpegDecoderAdapter(const decode::DecoderConfig& config)
    : impl_(std::make_unique<decode::FFmpegDecoder>(config)) {}

FFmpegDecoderAdapter::~FFmpegDecoderAdapter() = default;

bool FFmpegDecoderAdapter::Open() { return impl_->Open(); }

int FFmpegDecoderAdapter::SeekPreciseToMs(int64_t target_ms) {
  return impl_->SeekPreciseToMs(target_ms);
}

RationalFps FFmpegDecoderAdapter::GetVideoRationalFps() { return impl_->GetVideoRationalFps(); }

bool FFmpegDecoderAdapter::DecodeFrameToBuffer(buffer::Frame& output_frame) {
  return impl_->DecodeFrameToBuffer(output_frame);
}

bool FFmpegDecoderAdapter::GetPendingAudioFrame(buffer::AudioFrame& output_frame) {
  return impl_->GetPendingAudioFrame(output_frame);
}

bool FFmpegDecoderAdapter::IsEOF() const { return impl_->IsEOF(); }

void FFmpegDecoderAdapter::SetInterruptFlags(const DecoderInterruptFlags& flags) {
  decode::FFmpegDecoder::InterruptFlags f;
  f.fill_stop = flags.fill_stop;
  f.session_stop = flags.session_stop;
  impl_->SetInterruptFlags(f);
}

bool FFmpegDecoderAdapter::HasAudioStream() const {
  return impl_->HasAudioStream();
}

blockplan::PumpResult FFmpegDecoderAdapter::PumpDecoderOnce(blockplan::PumpMode mode) {
  return impl_->PumpDecoderOnce(mode);
}

}  // namespace retrovue::blockplan
