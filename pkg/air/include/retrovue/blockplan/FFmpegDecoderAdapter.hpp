// Repository: Retrovue-playout
// Component: FFmpegDecoderAdapter
// Purpose: Wraps decode::FFmpegDecoder to implement ITickProducerDecoder.
//          Used by TickProducer in production; tests inject FakeTickProducerDecoder instead.
// Copyright (c) 2025 RetroVue

#ifndef RETROVUE_BLOCKPLAN_FFMPEG_DECODER_ADAPTER_HPP_
#define RETROVUE_BLOCKPLAN_FFMPEG_DECODER_ADAPTER_HPP_

#include <memory>

#include "retrovue/blockplan/ITickProducerDecoder.hpp"
#include "retrovue/decode/FFmpegDecoder.h"

namespace retrovue::blockplan {

class FFmpegDecoderAdapter : public ITickProducerDecoder {
 public:
  explicit FFmpegDecoderAdapter(const decode::DecoderConfig& config);
  ~FFmpegDecoderAdapter() override;

  bool Open() override;
  int SeekPreciseToMs(int64_t target_ms) override;
  double GetVideoFPS() override;
  bool DecodeFrameToBuffer(buffer::Frame& output_frame) override;
  bool GetPendingAudioFrame(buffer::AudioFrame& output_frame) override;
  bool IsEOF() const override;
  void SetInterruptFlags(const DecoderInterruptFlags& flags) override;
  bool HasAudioStream() const override;

 private:
  std::unique_ptr<decode::FFmpegDecoder> impl_;
};

}  // namespace retrovue::blockplan

#endif  // RETROVUE_BLOCKPLAN_FFMPEG_DECODER_ADAPTER_HPP_
