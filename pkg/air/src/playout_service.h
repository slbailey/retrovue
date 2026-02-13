// Repository: Retrovue-playout
// Component: PlayoutControl gRPC Service Implementation
// Purpose: Implements the PlayoutControl service interface for channel lifecycle management.
// Copyright (c) 2025 RetroVue

#ifndef RETROVUE_PLAYOUT_SERVICE_H_
#define RETROVUE_PLAYOUT_SERVICE_H_

#include <atomic>
#include <chrono>
#include <condition_variable>
#include <memory>
#include <mutex>
#include <optional>
#include <thread>
#include <unordered_map>
#include <vector>

#include <grpcpp/grpcpp.h>

#include "playout.grpc.pb.h"
#include "playout.pb.h"
#include "retrovue/blockplan/BlockPlanSessionTypes.hpp"
#include "retrovue/blockplan/BlockPlanTypes.hpp"
#include "retrovue/blockplan/IPlayoutExecutionEngine.hpp"
#include "retrovue/runtime/PlayoutInterface.h"

namespace retrovue {
namespace playout {

// PlayoutControlImpl implements the gRPC service defined in playout.proto.
// This is a thin adapter that delegates to PlayoutInterface.
class PlayoutControlImpl final : public PlayoutControl::Service {
 public:
  // Constructs the service with a controller that manages channel lifecycle.
  // control_surface_only: when true, AttachStream writes HELLO (Phase 8.0 tests); when false, stream stays silent until SwitchToLive writes real MPEG-TS (Phase 8.6).
  // forensic_dump_dir: if non-empty, auto-enable TS forensic dump to <dir>/channel_<id>.ts
  PlayoutControlImpl(std::shared_ptr<runtime::PlayoutInterface> interface,
                     bool control_surface_only = false,
                     const std::string& forensic_dump_dir = "");
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

  // ==========================================================================
  // BlockPlan Mode RPCs
  // ==========================================================================

  grpc::Status StartBlockPlanSession(grpc::ServerContext* context,
                                      const StartBlockPlanSessionRequest* request,
                                      StartBlockPlanSessionResponse* response) override;

  grpc::Status FeedBlockPlan(grpc::ServerContext* context,
                              const FeedBlockPlanRequest* request,
                              FeedBlockPlanResponse* response) override;

  grpc::Status StopBlockPlanSession(grpc::ServerContext* context,
                                     const StopBlockPlanSessionRequest* request,
                                     StopBlockPlanSessionResponse* response) override;

  // Server-streaming RPC for block lifecycle events.
  // Core subscribes to receive BlockCompleted events for boundary-driven feeding.
  grpc::Status SubscribeBlockEvents(grpc::ServerContext* context,
                                     const SubscribeBlockEventsRequest* request,
                                     grpc::ServerWriter<BlockEvent>* writer) override;

 private:
  // Controller that manages all channel lifecycle operations
  std::shared_ptr<runtime::PlayoutInterface> interface_;

  // Phase 9.0: OutputBus/OutputSink architecture
  // control_surface_only_: when true, uses legacy HelloLoop; when false, uses MpegTSOutputSink
  bool control_surface_only_ = false;

  // Forensic dump: if non-empty, auto-enable TS dump to <dir>/channel_<id>.ts
  std::string forensic_dump_dir_;

  // Phase 9.0: gRPC layer owns only transport state (FD), not output runtime state.
  // Output runtime (encoder, queues, mux thread) is owned by MpegTSOutputSink in OutputBus.
  struct StreamState {
    int fd = -1;                    // UDS file descriptor (owned by gRPC layer)
    std::thread hello_thread;       // Legacy HelloLoop thread (control_surface_only_ mode only)
    std::atomic<bool> stop{false};  // Stop flag for HelloLoop
  };
  std::mutex stream_mutex_;
  std::unordered_map<int32_t, std::unique_ptr<StreamState>> stream_states_;

  // Legacy HelloLoop for control_surface_only_ mode
  static void HelloLoop(StreamState* state);

  // Call with stream_mutex_ held or from destructor.
  void DetachStreamLocked(int32_t channel_id, bool force);

  // INV-FINALIZE-LIVE: Create sink (if FD exists), attach, and wire program_output.
  // Call after SwitchToLive success or AttachStream (late attach path).
  // Requires stream_mutex_ held.
  void TryAttachSinkForChannel(int32_t channel_id);

  // ==========================================================================
  // BlockPlan Session State
  // ==========================================================================

  // Type alias: FedBlock replaces the former nested BlockPlanBlock.
  using BlockPlanBlock = blockplan::FedBlock;

  // Session state extends BlockPlanSessionContext (engine-visible base) with
  // gRPC-specific fields. Inheritance preserves all field access patterns.
  struct BlockPlanSessionState : blockplan::BlockPlanSessionContext {
    bool active = false;
    int32_t blocks_fed = 0;

    // Execution engine (owns the execution thread)
    // INV-SERIAL-BLOCK-EXECUTION: Engine selected by PlayoutExecutionMode
    std::unique_ptr<blockplan::IPlayoutExecutionEngine> engine;

    // Event subscribers (for SubscribeBlockEvents streaming)
    std::mutex event_mutex;
    std::vector<grpc::ServerWriter<BlockEvent>*> event_subscribers;
    std::string termination_reason;  // Set when session ends
  };

  // Convert proto BlockPlan to internal FedBlock type
  static BlockPlanBlock ProtoToBlock(const BlockPlan& proto);

  // Emit BlockCompleted event to all subscribers
  void EmitBlockCompleted(BlockPlanSessionState* state, const BlockPlanBlock& block,
                          int64_t final_ct_ms);

  // Emit BlockStarted event to all subscribers
  void EmitBlockStarted(BlockPlanSessionState* state, const BlockPlanBlock& block);

  // Emit SessionEnded event to all subscribers
  void EmitSessionEnded(BlockPlanSessionState* state, const std::string& reason);

  std::mutex blockplan_mutex_;
  std::unique_ptr<BlockPlanSessionState> blockplan_session_;
};

}  // namespace playout
}  // namespace retrovue

#endif  // RETROVUE_PLAYOUT_SERVICE_H_

