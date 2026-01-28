// Repository: Retrovue-playout
// Component: PlayoutControl gRPC Service Implementation
// Purpose: Implements the PlayoutControl service interface for channel lifecycle management.
// Copyright (c) 2025 RetroVue

#ifndef RETROVUE_PLAYOUT_SERVICE_H_
#define RETROVUE_PLAYOUT_SERVICE_H_

#include <atomic>
#include <chrono>
#include <memory>
#include <mutex>
#include <optional>
#include <thread>
#include <unordered_map>

#include <grpcpp/grpcpp.h>

#include "playout.grpc.pb.h"
#include "playout.pb.h"
#include "retrovue/runtime/PlayoutController.h"
#include "retrovue/telemetry/MetricsExporter.h"
#include "retrovue/timing/MasterClock.h"

namespace retrovue {
namespace playout {

// PlayoutControlImpl implements the gRPC service defined in playout.proto.
// This is a thin adapter that delegates to PlayoutController.
class PlayoutControlImpl final : public PlayoutControl::Service {
 public:
  // Constructs the service with a controller that manages channel lifecycle.
  // control_surface_only: when true, AttachStream writes HELLO (Phase 8.0 tests); when false, stream stays silent until SwitchToLive writes real MPEG-TS (Phase 8.6).
  PlayoutControlImpl(std::shared_ptr<runtime::PlayoutController> controller,
                     bool control_surface_only = false);
  ~PlayoutControlImpl() override;

  // Disable copy and move
  PlayoutControlImpl(const PlayoutControlImpl&) = delete;
  PlayoutControlImpl& operator=(const PlayoutControlImpl&) = delete;

  // RPC implementations
  grpc::Status StartChannel(grpc::ServerContext* context,
                            const StartChannelRequest* request,
                            StartChannelResponse* response) override;

  grpc::Status UpdatePlan(grpc::ServerContext* context,
                          const UpdatePlanRequest* request,
                          UpdatePlanResponse* response) override;

  grpc::Status StopChannel(grpc::ServerContext* context,
                           const StopChannelRequest* request,
                           StopChannelResponse* response) override;

  grpc::Status GetVersion(grpc::ServerContext* context,
                          const ApiVersionRequest* request,
                          ApiVersion* response) override;

  grpc::Status LoadPreview(grpc::ServerContext* context,
                           const LoadPreviewRequest* request,
                           LoadPreviewResponse* response) override;

  grpc::Status SwitchToLive(grpc::ServerContext* context,
                            const SwitchToLiveRequest* request,
                            SwitchToLiveResponse* response) override;

  // Phase 8.0: byte transport (Python UDS server, Air writes bytes)
  grpc::Status AttachStream(grpc::ServerContext* context,
                            const AttachStreamRequest* request,
                            AttachStreamResponse* response) override;

  grpc::Status DetachStream(grpc::ServerContext* context,
                            const DetachStreamRequest* request,
                            DetachStreamResponse* response) override;

 private:
  // Controller that manages all channel lifecycle operations
  std::shared_ptr<runtime::PlayoutController> controller_;

  // Phase 8.0/8.6: per-channel stream writer (UDS client). When control_surface_only_, writes HELLO; else no writer until SwitchToLive (real TS only).
  bool control_surface_only_ = false;
  struct StreamWriterState;
  std::mutex stream_mutex_;
  std::unordered_map<int32_t, std::unique_ptr<StreamWriterState>> stream_writers_;

  // Call with stream_mutex_ held or from destructor.
  void DetachStreamLocked(int32_t channel_id, bool force);
};

}  // namespace playout
}  // namespace retrovue

#endif  // RETROVUE_PLAYOUT_SERVICE_H_

