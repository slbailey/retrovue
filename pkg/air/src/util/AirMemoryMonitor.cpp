// Repository: Retrovue-playout
// Component: AIR Memory Monitor
// Purpose: Production-safe memory diagnostics with auto-trigger.
// Copyright (c) 2026 RetroVue

#include "retrovue/util/AirMemoryMonitor.hpp"
#include "retrovue/util/MemoryUtils.hpp"
#include "retrovue/util/Logger.hpp"

#include <cstdio>
#include <cstdlib>

namespace retrovue::util {

// ── Singleton state ──────────────────────────────────────────────────
static AirMemCounters g_counters;
static std::atomic<bool> g_diag_enabled{false};
static std::atomic<size_t> g_baseline_heap_mb{0};
static std::atomic<size_t> g_prev_heap_mb{0};

// Heap growth threshold (MB per window) to auto-enable diagnostics.
static constexpr size_t kAutoTriggerThresholdMB = 8;

AirMemCounters& GetAirMemCounters() {
  return g_counters;
}

bool IsMemDiagEnabled() {
  return g_diag_enabled.load(std::memory_order_relaxed);
}

void EnableMemDiag() {
  if (!g_diag_enabled.exchange(true, std::memory_order_relaxed)) {
    Logger::Info("[AIR_MEM] Memory diagnostic mode ENABLED");
  }
}

void InitMemDiag() {
  size_t heap_mb = GetHeapAllocatedBytes() / (1024 * 1024);
  g_baseline_heap_mb.store(heap_mb, std::memory_order_relaxed);
  g_prev_heap_mb.store(heap_mb, std::memory_order_relaxed);

  // Check env for explicit enable.
  const char* env = std::getenv("RETROVUE_MEM_DIAG");
  if (env && env[0] == '1') {
    g_diag_enabled.store(true, std::memory_order_relaxed);
    Logger::Info("[AIR_MEM] Memory diagnostic mode ENABLED via RETROVUE_MEM_DIAG=1");
  }

  // Always log baseline (single line, regardless of diag state).
  size_t rss_mb = GetRSSMB();
  char buf[128];
  snprintf(buf, sizeof(buf), "[AIR_MEM] baseline rss_mb=%zu heap_mb=%zu diag=%s",
           rss_mb, heap_mb, g_diag_enabled.load(std::memory_order_relaxed) ? "on" : "off");
  Logger::Info(std::string(buf));
}

// ── Logging (gated by diag flag) ─────────────────────────────────────

void LogMemorySnapshotEx(const SubsystemSizes& sub) {
  size_t heap_mb = GetHeapAllocatedBytes() / (1024 * 1024);

  // Auto-trigger: check heap growth even when diag is off.
  // This is the only work done per window when diag is disabled.
  size_t prev = g_prev_heap_mb.load(std::memory_order_relaxed);
  g_prev_heap_mb.store(heap_mb, std::memory_order_relaxed);

  if (AIR_MEM_UNLIKELY(!g_diag_enabled.load(std::memory_order_relaxed))) {
    // Auto-trigger check: if heap grew more than threshold since last window.
    if (prev > 0 && heap_mb > prev + kAutoTriggerThresholdMB) {
      g_diag_enabled.store(true, std::memory_order_relaxed);
      char tbuf[192];
      snprintf(tbuf, sizeof(tbuf),
          "[AIR_MEM] AUTO-TRIGGER: heap grew %zu→%zu MB (+%zu) in one window, threshold=%zu — diagnostics ENABLED",
          prev, heap_mb, heap_mb - prev, kAutoTriggerThresholdMB);
      Logger::Warn(std::string(tbuf));
      // Fall through to emit the first diagnostic snapshot.
    } else {
      return;  // Diag off and no trigger — skip all logging.
    }
  }

  // ── Full diagnostic snapshot ───────────────────────────────────────
  size_t rss_mb = GetRSSMB();
  size_t baseline = g_baseline_heap_mb.load(std::memory_order_relaxed);
  int64_t delta_mb = static_cast<int64_t>(heap_mb) - static_cast<int64_t>(baseline);

  int64_t segs     = g_counters.total_segment_transitions.load(std::memory_order_relaxed);
  int64_t reopens  = g_counters.total_decoder_reopens.load(std::memory_order_relaxed);
  int64_t decoded  = g_counters.total_frames_decoded.load(std::memory_order_relaxed);
  int64_t emitted  = g_counters.total_frames_emitted.load(std::memory_order_relaxed);

  char buf[512];
  snprintf(buf, sizeof(buf),
      "[AIR_MEM] rss_mb=%zu delta_mb=%lld heap_mb=%zu"
      " segs=%lld reopens=%lld decoded=%lld emitted=%lld"
      " sk_q=%zu vid_store=%zu aud_ms=%zu",
      rss_mb,
      static_cast<long long>(delta_mb),
      heap_mb,
      static_cast<long long>(segs),
      static_cast<long long>(reopens),
      static_cast<long long>(decoded),
      static_cast<long long>(emitted),
      sub.socket_sink_queue_bytes,
      sub.video_store_size,
      sub.audio_buffer_depth_ms);

  Logger::Info(std::string(buf));
}

void LogSegmentTransitionMemory() {
  if (AIR_MEM_UNLIKELY(!g_diag_enabled.load(std::memory_order_relaxed))) {
    return;
  }

  size_t rss_mb = GetRSSMB();
  size_t heap_mb = GetHeapAllocatedBytes() / (1024 * 1024);
  size_t baseline = g_baseline_heap_mb.load(std::memory_order_relaxed);
  int64_t delta_mb = static_cast<int64_t>(heap_mb) - static_cast<int64_t>(baseline);

  int64_t segs    = g_counters.total_segment_transitions.load(std::memory_order_relaxed);
  int64_t reopens = g_counters.total_decoder_reopens.load(std::memory_order_relaxed);

  char buf[192];
  snprintf(buf, sizeof(buf),
      "[AIR_SEG] segs=%lld rss_mb=%zu delta_mb=%lld reopens=%lld",
      static_cast<long long>(segs),
      rss_mb,
      static_cast<long long>(delta_mb),
      static_cast<long long>(reopens));

  Logger::Info(std::string(buf));
}

}  // namespace retrovue::util
