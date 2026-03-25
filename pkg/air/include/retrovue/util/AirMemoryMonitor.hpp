// Repository: Retrovue-playout
// Component: AIR Memory Monitor
// Purpose: Production-safe memory diagnostics with auto-trigger on growth.
//          Disabled by default.  Near-zero overhead when off.
//          Counters (atomic increments) are always active.
//          Logging and heap sampling only run when enabled.
// Copyright (c) 2026 RetroVue

#ifndef RETROVUE_UTIL_AIR_MEMORY_MONITOR_HPP_
#define RETROVUE_UTIL_AIR_MEMORY_MONITOR_HPP_

#include <atomic>
#include <cstddef>
#include <cstdint>

#ifdef __GNUC__
#define AIR_MEM_UNLIKELY(x) __builtin_expect(!!(x), 0)
#else
#define AIR_MEM_UNLIKELY(x) (x)
#endif

namespace retrovue::util {

// ── Global atomic counters (always active — negligible cost) ─────────
struct AirMemCounters {
  std::atomic<int64_t> total_segment_transitions{0};
  std::atomic<int64_t> total_decoder_reopens{0};
  std::atomic<int64_t> total_frames_decoded{0};
  std::atomic<int64_t> total_frames_emitted{0};
};

AirMemCounters& GetAirMemCounters();

// ── Diagnostic mode control ──────────────────────────────────────────

// Returns true if diagnostic logging is active.
bool IsMemDiagEnabled();

// Enable diagnostic logging.  Idempotent.
void EnableMemDiag();

// Initialize baseline RSS and check RETROVUE_MEM_DIAG env.
// Call once from main() at startup.
void InitMemDiag();

// ── Periodic logging (only emits when diag enabled) ──────────────────

struct SubsystemSizes {
  size_t socket_sink_queue_bytes = 0;
  size_t evidence_spool_records = 0;
  size_t evidence_spool_bytes = 0;
  size_t mux_interleaver_depth = 0;
  size_t video_store_size = 0;
  size_t audio_buffer_depth_ms = 0;
};

// Emit [AIR_MEM] + [AIR_WINDOW] if diag enabled.  No-op otherwise.
// Also checks for heap growth auto-trigger.
// Call every ~900 ticks from the tick loop.
void LogMemorySnapshotEx(const SubsystemSizes& sub);

// Emit [AIR_SEG] on segment transition if diag enabled.  No-op otherwise.
void LogSegmentTransitionMemory();

}  // namespace retrovue::util

#endif  // RETROVUE_UTIL_AIR_MEMORY_MONITOR_HPP_
