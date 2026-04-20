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

  // Low-level backward keyframe seek. Uses AVSEEK_FLAG_BACKWARD so the
  // seek lands on the nearest preceding keyframe; decode resumes from
  // there. The first emitted post-seek frame may precede `offset_ms`
  // by up to one GOP.
  //
  // THIS IS AN INTERNAL MECHANISM, NOT A FRAME-ACCURATE ENTRY POINT.
  // INV-SEAM-LATE-SUCCESSOR-JIP-001 requires frame-accurate entry.
  // Seam-recovery callers MUST use SeekFrameAccurate (below) instead.
  //
  // Returns false if the producer is not in Prepared/Activated lifecycle,
  // has no video stream, or the seek call itself fails.
  bool SeekTo(int64_t offset_ms);

  // Frame-accurate seek per INV-SEAM-LATE-SUCCESSOR-JIP-001. Performs
  // backward keyframe seek + forward decode-and-discard until the first
  // queued video frame's source_pts_us is at-or-after `offset_ms * 1000`.
  // Discards audio blocks whose end PTS is before the target (up to one
  // block of slop is acceptable; audio-sample precision is out of scope
  // for v1 frame-accurate JIP — the invariant's frame contract is on
  // video presentation timestamps).
  //
  // After a successful call, the NEXT PullVideo returns the first
  // at-or-after-target frame, satisfying the seam entry contract. The
  // caller (AirSession at pad-bridge exit) MUST NOT activate the seam
  // until this call returns.
  //
  // Runs on the caller's thread (typically the encode thread during
  // seam fire). Blocks until the target frame is decoded or EOF is
  // hit. For normal GOP sizes this is sub-100ms; pathological GOP
  // structures (keyframe-every-10s) could stall longer. This is a
  // known real-time trade-off for v1; asynchronous pre-seek during
  // pad bridge is a future optimisation.
  //
  // Returns false if SeekTo fails; returns true otherwise, even if
  // EOF is reached before the target (in which case subsequent
  // PullVideo returns nullopt — caller sees an empty successor).
  bool SeekFrameAccurate(int64_t offset_ms);

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
