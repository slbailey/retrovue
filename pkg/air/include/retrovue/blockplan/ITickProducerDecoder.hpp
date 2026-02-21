// Repository: Retrovue-playout
// Component: ITickProducerDecoder
// Purpose: Minimal decoder interface for TickProducer so tests can inject
//          a fake decoder (deterministic DROP duration/PTS contract tests).
//          Production uses FFmpegDecoderAdapter; tests use FakeTickProducerDecoder.
// Contract Reference: INV-FPS-MAPPING, INV-FPS-TICK-PTS
// Copyright (c) 2025 RetroVue

#ifndef RETROVUE_BLOCKPLAN_ITICK_PRODUCER_DECODER_HPP_
#define RETROVUE_BLOCKPLAN_ITICK_PRODUCER_DECODER_HPP_

#include <atomic>
#include <cstdint>
#include <functional>
#include <memory>
#include <string>

#include "retrovue/buffer/FrameRingBuffer.h"

namespace retrovue::blockplan {

// Interrupt flags for decoder I/O (matches FFmpegDecoder::InterruptFlags).
struct DecoderInterruptFlags {
  std::atomic<bool>* fill_stop = nullptr;
  std::atomic<bool>* session_stop = nullptr;
};

// Minimal decoder surface used by TickProducer. Implemented by FFmpegDecoderAdapter
// (production) and FakeTickProducerDecoder (tests).
class ITickProducerDecoder {
 public:
  virtual ~ITickProducerDecoder() = default;

  virtual bool Open() = 0;
  virtual int SeekPreciseToMs(int64_t target_ms) = 0;
  virtual double GetVideoFPS() = 0;
  virtual bool DecodeFrameToBuffer(buffer::Frame& output_frame) = 0;
  virtual bool GetPendingAudioFrame(buffer::AudioFrame& output_frame) = 0;
  virtual bool IsEOF() const = 0;
  virtual void SetInterruptFlags(const DecoderInterruptFlags& flags) = 0;
  // True if the asset has an audio stream (for INV-AUDIO-PRIME-002 / priming logs).
  virtual bool HasAudioStream() const { return false; }
};

}  // namespace retrovue::blockplan

#endif  // RETROVUE_BLOCKPLAN_ITICK_PRODUCER_DECODER_HPP_
