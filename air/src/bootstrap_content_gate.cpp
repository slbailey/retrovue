// AIR vNext — BootstrapContentGate implementation.

#include "bootstrap_content_gate.hpp"

namespace retrovue::air {

BootstrapContentGate::Verdict BootstrapContentGate::Evaluate(
    const ReadinessSnapshot& snapshot) {
  ++evaluations_;

  if (fired_) return Verdict::Ready;  // sticky

  if (!snapshot.decoder_healthy) return Verdict::NotReady;
  if (snapshot.video_buffer_depth < cfg_.min_video_frames) return Verdict::NotReady;
  if (snapshot.audio_buffer_depth < cfg_.min_audio_blocks) return Verdict::NotReady;

  fired_ = true;
  ticks_to_fire_ = evaluations_;
  return Verdict::Ready;
}

}  // namespace retrovue::air
