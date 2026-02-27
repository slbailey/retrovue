// Repository: Retrovue-playout
// Component: Sink diagnostics for broken-pipe debugging
// Purpose: Hook A (first write failure log), Hook B (CLOSE_FD), Hook C (EPIPE latch).
// Copyright (c) 2025 RetroVue

#ifndef RETROVUE_OUTPUT_SINK_DIAGNOSTICS_H_
#define RETROVUE_OUTPUT_SINK_DIAGNOSTICS_H_

#include <atomic>
#include <cstdint>
#include <string>
#include <thread>

namespace retrovue::output {

// Output kind for Hook A (identify the target of the broken pipe).
enum class OutputKind {
  kSocket,
  kSubprocessStdin,
  kFifo,
  kAvio,
};

// Thread-local tick context set by the tick loop so write callback can log it on first failure.
void SetTickContext(int64_t tick, const std::string& block_id);
void GetTickContext(int64_t* tick, std::string* block_id);

// Hook A: Log once per (sink_ptr) when first write_frame failed.
// Call from write callback or send() error path. Returns true if this call did the log.
bool LogFirstWriteFailure(
    OutputKind output_kind,
    int fd,
    void* sink_ptr,
    uint64_t sink_generation,
    const char* subprocess_pid_poll_exit = nullptr  // e.g. "pid=12345 poll=0 exit=0" or "n/a"
);

// Hook B: Close fd with diagnostic log (file:line, thread, sink_generation).
// Use macro CLOSE_FD(fd, reason) or CLOSE_FD(fd, reason, sink_generation).
void CloseFdWithLog(int fd, const char* reason, const char* file, int line,
                    int64_t sink_generation = -1);

}  // namespace retrovue::output

// Hook B macro: instrument all closes/detaches of output fds.
// Pass -1 for sink_generation when not available.
#define CLOSE_FD(fd, reason, sink_generation) \
  ::retrovue::output::CloseFdWithLog((fd), (reason), __FILE__, __LINE__, (sink_generation))

#endif  // RETROVUE_OUTPUT_SINK_DIAGNOSTICS_H_
