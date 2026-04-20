// AIR vNext — BootstrapContentGate.
//
// Narrow, sticky gate that decides when a warming session may transition
// to on-air. First Evaluate() returning Ready is the sign-on moment; every
// subsequent Evaluate() returns Ready too (sticky — never regresses).
//
// Per lifecycle design note (LIFECYCLE_DESIGN.md), the gate fires exactly
// once per session. Retune is a separate transition class that would use
// a different gate, not a re-arming of this one.
//
// Evaluated against a ReadinessSnapshot that the caller assembles each
// tick. This first implementation keeps the signal set minimal (buffer
// depths + decoder health); per the design doc, PTS monotonicity and A/V
// alignment are true by Normalizer construction and trusted here without
// re-checking. Signals can be tightened later as needed.
//
// Related memory:
//   - project_retrovue_air_lifecycle_model (bootstrap semantics)
//   - project_retrovue_air_execution_discipline (aggregate readiness)

#ifndef AIR_BOOTSTRAP_CONTENT_GATE_HPP_
#define AIR_BOOTSTRAP_CONTENT_GATE_HPP_

#include <cstddef>
#include <cstdint>

namespace retrovue::air {

class BootstrapContentGate {
 public:
  struct Config {
    // Minimum buffered video frames before the gate may fire. Default ~1
    // second at 30fps — reasonable runway for encoder + transport hiccups.
    std::size_t min_video_frames = 30;
    // Minimum buffered audio blocks (as emitted by Normalizer.PullAudio,
    // which is one block per channel-frame period).
    std::size_t min_audio_blocks = 30;
  };

  struct ReadinessSnapshot {
    std::size_t video_buffer_depth = 0;
    std::size_t audio_buffer_depth = 0;
    bool decoder_healthy = true;
  };

  enum class Verdict { NotReady, Ready };

  BootstrapContentGate() = default;
  explicit BootstrapContentGate(Config cfg) : cfg_(cfg) {}

  // Evaluate readiness against the current snapshot. Returns Ready the
  // first time all conditions are met; subsequently sticky (returns Ready
  // forever). Each call increments the evaluation counter, which is the
  // basis for TicksToFire diagnostics.
  Verdict Evaluate(const ReadinessSnapshot& snapshot);

  // True once the gate has ever returned Ready.
  bool HasFired() const { return fired_; }

  // Number of Evaluate() calls before the first Ready. Zero if never fired.
  std::int64_t TicksToFire() const { return ticks_to_fire_; }

  // Total Evaluate() calls to date.
  std::int64_t Evaluations() const { return evaluations_; }

  const Config& GetConfig() const { return cfg_; }

 private:
  Config cfg_;
  bool fired_ = false;
  std::int64_t ticks_to_fire_ = 0;
  std::int64_t evaluations_ = 0;
};

}  // namespace retrovue::air

#endif  // AIR_BOOTSTRAP_CONTENT_GATE_HPP_
