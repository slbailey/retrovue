// Repository: Retrovue-playout
// Component: PlayoutControl gRPC Server
// Purpose: Main entry point for the RetroVue playout engine.
// Copyright (c) 2025 RetroVue

#include <signal.h>
#include <execinfo.h>
#include <unistd.h>

#include <chrono>
#include <cstdio>
#include <iostream>
#include <memory>
#include <string>

extern "C" {
#include <libavformat/avformat.h>
}

#include <grpcpp/grpcpp.h>
#include <grpcpp/health_check_service_interface.h>
#include <grpcpp/ext/proto_server_reflection_plugin.h>

#include "playout_service.h"
#include "retrovue/runtime/PlayoutEngine.h"
#include "retrovue/runtime/PlayoutInterface.h"
#include "retrovue/output/SinkDiagnostics.h"
#include "retrovue/telemetry/MetricsExporter.h"
#include "retrovue/timing/MasterClock.h"

namespace {

void crash_handler(int sig) {
  void* array[50];
  size_t size = backtrace(array, 50);
  std::fprintf(stderr, "FATAL SIGNAL %d\n", sig);
  backtrace_symbols_fd(array, static_cast<int>(size), STDERR_FILENO);
  _exit(1);
}

// =========================================================================
// AIR_SHUTDOWN signal handlers (async-signal-safe: write(2) only)
// =========================================================================
// Pre-formatted message buffers. pid is patched once at startup.
// SIGPIPE: log but do NOT exit — let the EPIPE path handle recovery.
// SIGTERM/SIGINT: log and _exit immediately.
// =========================================================================
static volatile sig_atomic_t g_signal_shutdown_logged = 0;

// Fixed-size buffers for async-signal-safe output. Pid patched at init.
static char g_sigpipe_msg[256];
static char g_sigterm_msg[256];
static char g_sigint_msg[256];
static int g_sigpipe_msg_len = 0;
static int g_sigterm_msg_len = 0;
static int g_sigint_msg_len = 0;

static void init_signal_messages() {
  pid_t pid = ::getpid();
  g_sigpipe_msg_len = snprintf(g_sigpipe_msg, sizeof(g_sigpipe_msg),
      "[AIR_SHUTDOWN] AIR_SHUTDOWN channel=0 pid=%d reason=signal_received"
      " details=SIGPIPE block_id=unknown segment_index=-1 frame=-1\n", pid);
  g_sigterm_msg_len = snprintf(g_sigterm_msg, sizeof(g_sigterm_msg),
      "[AIR_SHUTDOWN] AIR_SHUTDOWN channel=0 pid=%d reason=signal_received"
      " details=SIGTERM block_id=unknown segment_index=-1 frame=-1\n", pid);
  g_sigint_msg_len = snprintf(g_sigint_msg, sizeof(g_sigint_msg),
      "[AIR_SHUTDOWN] AIR_SHUTDOWN channel=0 pid=%d reason=signal_received"
      " details=SIGINT block_id=unknown segment_index=-1 frame=-1\n", pid);
}

void sigpipe_handler(int) {
  if (g_signal_shutdown_logged) return;
  g_signal_shutdown_logged = 1;
  if (write(STDERR_FILENO, g_sigpipe_msg, static_cast<size_t>(g_sigpipe_msg_len)) < 0) { /* best-effort */ }
  // Do NOT _exit — let the write path see EPIPE and handle it.
}

void sigterm_handler(int sig) {
  if (g_signal_shutdown_logged) return;
  g_signal_shutdown_logged = 1;
  if (write(STDERR_FILENO, g_sigterm_msg, static_cast<size_t>(g_sigterm_msg_len)) < 0) { /* best-effort */ }
  _exit(128 + sig);
}

void sigint_handler(int sig) {
  if (g_signal_shutdown_logged) return;
  g_signal_shutdown_logged = 1;
  if (write(STDERR_FILENO, g_sigint_msg, static_cast<size_t>(g_sigint_msg_len)) < 0) { /* best-effort */ }
  _exit(128 + sig);
}

// Parse command-line arguments
struct ServerConfig {
  std::string server_address = "0.0.0.0:50051";
  bool enable_reflection = true;
  bool control_surface_only = false;  // Phase 8.0: no decode/render, AttachStream only
  std::string forensic_dump_dir;      // If set, auto-enable TS forensic dump for all sinks
};

ServerConfig ParseArgs(int argc, char** argv) {
  ServerConfig config;

  for (int i = 1; i < argc; ++i) {
    std::string arg = argv[i];
    
    if ((arg == "--port" || arg == "-p") && i + 1 < argc) {
      config.server_address = std::string("0.0.0.0:") + argv[++i];
    } else if (arg == "--address" || arg == "-a") {
      if (i + 1 < argc) {
        config.server_address = argv[++i];
      }
    } else if (arg == "--control-surface-only") {
      config.control_surface_only = true;
    } else if (arg == "--forensic-dump-dir" && i + 1 < argc) {
      config.forensic_dump_dir = argv[++i];
    } else if (arg == "--help" || arg == "-h") {
      std::cout << "RetroVue Playout Engine\n\n"
                << "Usage: retrovue_playout [OPTIONS]\n\n"
                << "Options:\n"
                << "  -p, --port PORT        Listen port (default: 50051)\n"
                << "  -a, --address ADDRESS  Full listen address (default: 0.0.0.0:50051)\n"
                << "  --control-surface-only Phase 8.0: no decode/render (StartChannel + AttachStream only)\n"
                << "  --forensic-dump-dir DIR  Mirror all TS output to DIR/channel_<id>.ts\n"
                << "  -h, --help             Show this help message\n"
                << std::endl;
      std::exit(0);
    }
  }

  return config;
}

void RunServer(const ServerConfig& config) {
  // Create and start metrics exporter (non-fatal: continue without metrics if port in use)
  auto metrics_exporter = std::make_shared<retrovue::telemetry::MetricsExporter>(9308);
  if (!metrics_exporter->Start()) {
    std::cerr << "Warning: metrics server failed to start (port 9308 may be in use), continuing without metrics"
              << std::endl;
  }

  const auto epoch_now = std::chrono::duration_cast<std::chrono::microseconds>(
      std::chrono::system_clock::now().time_since_epoch());
  auto master_clock = retrovue::timing::MakeSystemMasterClock(epoch_now.count(), 0.0);

  // Create the domain engine (contains tested domain logic)
  auto engine = std::make_shared<retrovue::runtime::PlayoutEngine>(
      metrics_exporter, master_clock, config.control_surface_only);
  
  // Create the controller (thin adapter between gRPC and domain)
  auto interface = std::make_shared<retrovue::runtime::PlayoutInterface>(engine);
  
  // Create the gRPC service (thin adapter between gRPC and interface)
  retrovue::playout::PlayoutControlImpl service(interface, config.control_surface_only,
                                                 config.forensic_dump_dir);

  // Enable health checking and reflection
  grpc::EnableDefaultHealthCheckService(true);
  grpc::reflection::InitProtoReflectionServerBuilderPlugin();

  // Build the server
  grpc::ServerBuilder builder;
  builder.AddListeningPort(config.server_address, grpc::InsecureServerCredentials());
  builder.RegisterService(&service);

  // Start the server
  std::unique_ptr<grpc::Server> server(builder.BuildAndStart());
  
  std::cout << "==============================================================" << std::endl;
  std::cout << "RetroVue Playout Engine (Phase 3)" << std::endl;
  std::cout << "==============================================================" << std::endl;
  std::cout << "gRPC Server: " << config.server_address << std::endl;
  std::cout << "API Version: 1.0.0" << std::endl;
  std::cout << "gRPC Health Check: Enabled" << std::endl;
  std::cout << "gRPC Reflection: " << (config.enable_reflection ? "Enabled" : "Disabled") << std::endl;
  std::cout << "Metrics Endpoint: http://localhost:9308/metrics" << std::endl;
  if (!config.forensic_dump_dir.empty()) {
    std::cout << "Forensic Dump: " << config.forensic_dump_dir << "/channel_<id>.ts" << std::endl;
  }
  std::cout << "==============================================================" << std::endl;
  std::cout << "\nComponents:" << std::endl;
  std::cout << "  ✓ FFmpegDecoder (real video decoding)" << std::endl;
  std::cout << "  ✓ FrameRingBuffer (lock-free circular buffer)" << std::endl;
  std::cout << "  ✓ ProgramOutput (headless mode)" << std::endl;
  std::cout << "  ✓ MetricsHTTPServer (Prometheus format)" << std::endl;
  std::cout << "\nPress Ctrl+C to shutdown...\n" << std::endl;

  // Wait for the server to shutdown
  server->Wait();
  
  // Cleanup metrics exporter
  metrics_exporter->Stop();
}

}  // namespace

int main(int argc, char** argv) {
  signal(SIGSEGV, crash_handler);
  signal(SIGABRT, crash_handler);
  signal(SIGILL, crash_handler);
  signal(SIGFPE, crash_handler);

  // AIR_SHUTDOWN: Signal handlers for graceful shutdown instrumentation
  init_signal_messages();
  signal(SIGPIPE, sigpipe_handler);
  signal(SIGTERM, sigterm_handler);
  signal(SIGINT,  sigint_handler);

  // AIR_SHUTDOWN: atexit fallback — fires only if no terminal reason was logged
  std::atexit([]() {
    if (!retrovue::output::AirShutdownFired()) {
      retrovue::output::ShutdownContext ctx;
      ctx.details = "atexit_no_prior_shutdown";
      retrovue::output::LogAirShutdown(
          retrovue::output::ShutdownReason::kUnexpectedProcessExit, ctx);
    }
  });

  // INV-FFMPEG-GLOBAL-INIT-001: Initialize FFmpeg global state before any
  // threads are spawned. Required for thread-safe network/TLS initialization.
  avformat_network_init();

  try {
    ServerConfig config = ParseArgs(argc, argv);
    RunServer(config);
    std::cout << "[AIR_SHUTDOWN] AIR_PROCESS_EXIT pid=" << static_cast<int>(::getpid())
              << " exit_code=0 reason=server_wait_returned" << std::endl;
    return 0;
  } catch (const std::exception& e) {
    std::cerr << "Fatal error: " << e.what() << std::endl;
    std::cerr << "[AIR_SHUTDOWN] AIR_PROCESS_EXIT pid=" << static_cast<int>(::getpid())
              << " exit_code=1 reason=exception" << std::endl;
    return 1;
  }
}

