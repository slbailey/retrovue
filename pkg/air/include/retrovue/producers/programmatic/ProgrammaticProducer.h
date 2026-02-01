// Phase 6A.3 — ProgrammaticProducer: TEMPORARY / test-only / non-domain.
// Scaffolding producer for synthetic frames; no ffmpeg/file I/O.
// Same lifecycle as FileProducer; honors start_offset_ms and hard_stop_time_ms.
// Will be replaced by domain-specific producers in the future. Do not expand its role.

#ifndef RETROVUE_PRODUCERS_PROGRAMMATIC_PROGRAMMATIC_PRODUCER_H_
#define RETROVUE_PRODUCERS_PROGRAMMATIC_PROGRAMMATIC_PRODUCER_H_

#include <atomic>
#include <cstdint>
#include <memory>
#include <string>
#include <thread>

#include "retrovue/buffer/FrameRingBuffer.h"
#include "retrovue/producers/IProducer.h"

namespace retrovue::timing
{
  class MasterClock;
}

namespace retrovue::producers::programmatic
{

  struct ProgrammaticProducerConfig
  {
    std::string asset_uri;
    int target_width = 1920;
    int target_height = 1080;
    double target_fps = 30.0;
    int64_t start_offset_ms = 0;
    int64_t hard_stop_time_ms = 0;
  };

  // Generates synthetic frames only. No file I/O, no ffmpeg.
  // Same IProducer lifecycle; works with preview/live slot logic (simple producer path).
  class ProgrammaticProducer : public retrovue::producers::IProducer
  {
  public:
    ProgrammaticProducer(
        const ProgrammaticProducerConfig& config,
        buffer::FrameRingBuffer& output_buffer,
        std::shared_ptr<timing::MasterClock> clock = nullptr);

    ~ProgrammaticProducer() override;

    ProgrammaticProducer(const ProgrammaticProducer&) = delete;
    ProgrammaticProducer& operator=(const ProgrammaticProducer&) = delete;

    bool start() override;
    void stop() override;
    bool isRunning() const override;
    void RequestStop() override;
    bool IsStopped() const override;

    std::optional<AsRunFrameStats> GetAsRunFrameStats() const override;

    uint64_t GetFramesProduced() const;

  private:
    enum class State { STOPPED, RUNNING, STOPPING };
    void ProduceLoop();

    ProgrammaticProducerConfig config_;
    buffer::FrameRingBuffer& output_buffer_;
    std::shared_ptr<timing::MasterClock> master_clock_;

    std::atomic<State> state_;
    std::atomic<bool> stop_requested_;
    std::atomic<uint64_t> frames_produced_;

    std::unique_ptr<std::thread> producer_thread_;
    int64_t frame_interval_us_;
    int64_t next_pts_us_;  // synthetic PTS (starts at start_offset_ms * 1000)
  };

}  // namespace retrovue::producers::programmatic

#endif  // RETROVUE_PRODUCERS_PROGRAMMATIC_PROGRAMMATIC_PRODUCER_H_
