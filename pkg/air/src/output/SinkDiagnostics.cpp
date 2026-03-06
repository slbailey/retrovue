// Repository: Retrovue-playout
// Component: Sink diagnostics for broken-pipe debugging
// Purpose: Hook A (first write failure log), Hook B (CLOSE_FD), Hook C support.
// Copyright (c) 2025 RetroVue

#include "retrovue/output/SinkDiagnostics.h"

#include <chrono>
#include <iostream>
#include <mutex>
#include <sstream>
#include <unordered_set>

#if defined(__linux__) || defined(__APPLE__)
#include <unistd.h>
#endif

namespace retrovue::output {

namespace {

// Thread-local tick context (set by tick loop so write callback can log on first failure).
thread_local int64_t g_tick = -1;
thread_local std::string g_block_id;

// Hook A: one-time log latch per sink_ptr so we only print once per sink.
std::mutex g_first_failure_mutex;
std::unordered_set<void*> g_first_failure_logged;

const char* OutputKindToString(OutputKind k) {
  switch (k) {
    case OutputKind::kSocket: return "socket";
    case OutputKind::kSubprocessStdin: return "subprocess_stdin";
    case OutputKind::kFifo: return "fifo";
    case OutputKind::kAvio: return "avio";
    default: return "unknown";
  }
}

}  // namespace

void SetTickContext(int64_t tick, const std::string& block_id) {
  g_tick = tick;
  g_block_id = block_id;
}

void GetTickContext(int64_t* tick, std::string* block_id) {
  if (tick) *tick = g_tick;
  if (block_id) *block_id = g_block_id;
}

bool LogFirstWriteFailure(
    OutputKind output_kind,
    int fd,
    void* sink_ptr,
    uint64_t sink_generation,
    const char* subprocess_pid_poll_exit) {
  if (!sink_ptr) return false;
  bool did_log = false;
  {
    std::lock_guard<std::mutex> lock(g_first_failure_mutex);
    if (g_first_failure_logged.find(sink_ptr) == g_first_failure_logged.end()) {
      g_first_failure_logged.insert(sink_ptr);
      did_log = true;
    }
  }
  if (!did_log) return false;

  int64_t tick = -1;
  std::string block_id;
  GetTickContext(&tick, &block_id);
  std::thread::id tid = std::this_thread::get_id();
  std::ostringstream oss;
  oss << "[EPIPE-FIRST] output_kind=" << OutputKindToString(output_kind)
      << " fd=" << fd
      << " sink_ptr=" << sink_ptr
      << " sink_generation=" << sink_generation;
  if (subprocess_pid_poll_exit && *subprocess_pid_poll_exit) {
    oss << " " << subprocess_pid_poll_exit;
  }
  oss << " tick=" << tick
      << " block_id=" << (block_id.empty() ? "n/a" : block_id)
      << " thread_id=" << tid;
  std::cerr << oss.str() << std::endl;
  return true;
}

void CloseFdWithLog(int fd, const char* reason, const char* file, int line,
                   int64_t sink_generation) {
  if (fd < 0) return;
  std::thread::id tid = std::this_thread::get_id();
  std::cerr << "[CLOSE_FD] file=" << file << " line=" << line
            << " thread_id=" << tid
            << " fd=" << fd
            << " sink_generation=" << (sink_generation >= 0 ? std::to_string(sink_generation) : "n/a")
            << " reason=" << (reason ? reason : "") << std::endl;
  ::close(fd);
}

// =========================================================================
// AIR_SHUTDOWN: Centralized shutdown summary event
// =========================================================================

namespace {

// Single-fire latch for terminal shutdown reasons.
std::atomic<bool> g_shutdown_fired{false};

// Global channel_id for signal handlers / atexit (set at session start).
std::atomic<int32_t> g_shutdown_channel_id{0};

const char* ShutdownReasonToString(ShutdownReason r) {
  switch (r) {
    case ShutdownReason::kChannelTeardown:       return "channel_teardown";
    case ShutdownReason::kOutputWriteFailure:    return "output_write_failure";
    case ShutdownReason::kSignalReceived:        return "signal_received";
    case ShutdownReason::kDecoderFailure:        return "decoder_failure";
    case ShutdownReason::kBlackModeEntered:      return "black_mode_entered";
    case ShutdownReason::kUnexpectedProcessExit: return "unexpected_process_exit";
    default: return "unknown";
  }
}

}  // namespace

bool LogAirShutdown(ShutdownReason reason, const ShutdownContext& ctx) {
  const bool is_non_terminal = (reason == ShutdownReason::kBlackModeEntered);

  if (!is_non_terminal) {
    // Terminal: first writer wins via CAS.
    bool expected = false;
    if (!g_shutdown_fired.compare_exchange_strong(expected, true,
            std::memory_order_acq_rel)) {
      return false;  // Already fired a terminal reason
    }
  }

  // Use channel_id from context, fall back to global.
  int32_t ch = ctx.channel_id;
  if (ch == 0) ch = g_shutdown_channel_id.load(std::memory_order_acquire);

  std::ostringstream oss;
  oss << "[AIR_SHUTDOWN] AIR_SHUTDOWN"
      << " channel=" << ch
      << " pid=" << static_cast<int>(::getpid())
      << " reason=" << ShutdownReasonToString(reason)
      << " details=" << (ctx.details.empty() ? "none" : ctx.details)
      << " block_id=" << (ctx.block_id.empty() ? "unknown" : ctx.block_id)
      << " segment_index=" << ctx.segment_index
      << " frame=" << ctx.frame_number;
  std::cerr << oss.str() << std::endl;
  return true;
}

bool AirShutdownFired() {
  return g_shutdown_fired.load(std::memory_order_acquire);
}

void SetAirShutdownChannelId(int32_t channel_id) {
  g_shutdown_channel_id.store(channel_id, std::memory_order_release);
}

}  // namespace retrovue::output
