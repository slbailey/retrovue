// Repository: Retrovue-playout
// Component: Playout Execution Engine Interface
// Purpose: Minimal interface for execution engine selection by mode
// Contract Reference: INV-SERIAL-BLOCK-EXECUTION, PlayoutAuthorityContract.md
// Copyright (c) 2025 RetroVue

#ifndef RETROVUE_BLOCKPLAN_IPLAYOUT_EXECUTION_ENGINE_HPP_
#define RETROVUE_BLOCKPLAN_IPLAYOUT_EXECUTION_ENGINE_HPP_

namespace retrovue::blockplan {

// =============================================================================
// IPlayoutExecutionEngine
// Minimal interface for playout execution engines.
// Does NOT expose timing, clocks, or content logic.
//
// Current implementations:
//   - SerialBlockExecutionEngine (kSerialBlock)
//   - ContinuousOutputExecutionEngine (kContinuousOutput) — P3.0 pad-only
// =============================================================================

class IPlayoutExecutionEngine {
 public:
  virtual ~IPlayoutExecutionEngine() = default;

  // Start the execution engine.
  // Spawns the execution thread and begins processing blocks from the queue.
  // Must be called exactly once per engine instance.
  virtual void Start() = 0;

  // Stop the execution engine.
  // Signals the execution thread to terminate and blocks until it exits.
  // Idempotent: safe to call multiple times or if never started.
  virtual void Stop() = 0;
};

}  // namespace retrovue::blockplan

#endif  // RETROVUE_BLOCKPLAN_IPLAYOUT_EXECUTION_ENGINE_HPP_
