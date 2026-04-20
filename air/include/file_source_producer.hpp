// AIR vNext — FileSourceProducer.
//
// Reads a media file via libav (FFmpeg C API). Decodes video to
// source-canonical YUV420P frames and audio to interleaved int16 PCM
// blocks at the source's native sample rate. Implements ISourceProducer
// for consumption by a per-source Normalizer downstream.
//
// Scope (slice 5):
//   - YUV420P input only. Non-YUV420P sources are rejected at Prepare.
//   - Audio is converted to S16 interleaved via swresample, at the
//     source's native sample rate. Rate conversion to channel rate is
//     the Normalizer's responsibility.
//   - Single video + single audio stream. Additional streams ignored.
//   - No seeking. Pulls decode forward from file start.
//   - Source PTS is converted from stream timebase to microseconds via
//     av_rescale_q (lossless rational conversion).
//
// Deferred (later slices):
//   - swscale pixel-format conversion for non-YUV420P sources.
//   - Seeking / JIP offsets at file level (vs. Normalizer-level).
//   - Multi-stream selection.
//   - Hardware decode paths.

#ifndef AIR_FILE_SOURCE_PRODUCER_HPP_
#define AIR_FILE_SOURCE_PRODUCER_HPP_

#include <cstdint>
#include <memory>
#include <optional>
#include <string>

#include "channel_canonical.hpp"
#include "source_producer.hpp"

namespace retrovue::air {

class FileSourceProducer : public ISourceProducer {
 public:
  struct Config {
    std::string file_path;
    // If true (default), Prepare fails when source video pixel format is
    // not YUV420P. Set to false to allow non-YUV420P (not supported until
    // swscale is wired in a later slice — reserved).
    bool require_yuv420p = true;
  };

  explicit FileSourceProducer(Config config);
  ~FileSourceProducer();

  FileSourceProducer(const FileSourceProducer&) = delete;
  FileSourceProducer& operator=(const FileSourceProducer&) = delete;

  // ISourceProducer
  bool Prepare() override;
  bool Activate() override;
  void Retire() override;
  std::optional<SourceVideoFrame> PullVideo() override;
  std::optional<SourceAudioBlock> PullAudio() override;
  ProducerHealth Health() const override;
  ProducerLifecycle Lifecycle() const override;

  // Seek to approximately `offset_ms` into the asset (good-enough v1).
  // Uses AVSEEK_FLAG_BACKWARD so the seek lands on the nearest preceding
  // keyframe; decode resumes from there. The first emitted post-seek
  // frame may therefore be up to one GOP earlier than the requested
  // offset. Caller is responsible for tolerating this (frame-accurate
  // JIP is a later refinement). Returns false if the producer is not in
  // Prepared/Activated lifecycle, has no video stream, or the seek call
  // itself fails. Used by AirSession to satisfy
  // INV-SEAM-LATE-SUCCESSOR-JIP-001 on pad-bridge exit.
  bool SeekTo(int64_t offset_ms);

  // Source-format accessors. Valid after Prepare() returns true.
  bool HasVideoStream() const;
  bool HasAudioStream() const;
  int VideoWidth() const;
  int VideoHeight() const;
  Rational VideoFrameRate() const;  // from container / stream metadata
  int AudioSampleRate() const;
  int AudioChannels() const;

  // Impl is forward-declared public so translation-unit-local helpers in
  // file_source_producer.cpp can reference it. The type is fully defined
  // only in the .cpp; external code cannot see its members.
  struct Impl;

 private:
  std::unique_ptr<Impl> impl_;
  Config config_;
  ProducerLifecycle lifecycle_ = ProducerLifecycle::kConstructed;
};

}  // namespace retrovue::air

#endif  // AIR_FILE_SOURCE_PRODUCER_HPP_
