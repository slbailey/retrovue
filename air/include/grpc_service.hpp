// AIR vNext — gRPC AirControl service implementation.
//
// Thin adapter that dispatches the two AirControl RPCs (StartChannel,
// StopChannel) to AirSession's three-phase startup + Close. No business
// logic lives here; this file is deliberately mechanical.
//
// Single session per process — session_ is a member, not a global. A
// mutex serializes access so StartChannel and StopChannel cannot race.
//
// Byte path (out-of-band): Core has already bound a Unix Domain Socket
// at StartChannelRequest.output_uds_path. This service connects to that
// UDS as a SOCK_STREAM client and hands the fd to session_.AttachOutput.

#ifndef AIR_GRPC_SERVICE_HPP_
#define AIR_GRPC_SERVICE_HPP_

#include <grpcpp/grpcpp.h>

#include <mutex>

#include "air_control.grpc.pb.h"
#include "air_session.hpp"

namespace retrovue::air {

class AirControlServiceImpl final
    : public retrovue::air::v1::AirControl::Service {
 public:
  AirControlServiceImpl() = default;

  grpc::Status StartChannel(
      grpc::ServerContext* context,
      const retrovue::air::v1::StartChannelRequest* request,
      retrovue::air::v1::StartChannelResponse* response) override;

  grpc::Status StopChannel(
      grpc::ServerContext* context,
      const retrovue::air::v1::StopChannelRequest* request,
      retrovue::air::v1::StopChannelResponse* response) override;

  grpc::Status GetSessionStatus(
      grpc::ServerContext* context,
      const retrovue::air::v1::GetSessionStatusRequest* request,
      retrovue::air::v1::GetSessionStatusResponse* response) override;

  // --- Execution queue surface (Phase A: stubs returning UNIMPLEMENTED) ---
  // Semantics land in Phase B (queue model) and Phase C (SeamController).
  grpc::Status SupplyBlock(
      grpc::ServerContext* context,
      const retrovue::air::v1::SupplyBlockRequest* request,
      retrovue::air::v1::SupplyBlockResponse* response) override;

  grpc::Status PutBlockRevision(
      grpc::ServerContext* context,
      const retrovue::air::v1::PutBlockRevisionRequest* request,
      retrovue::air::v1::PutBlockRevisionResponse* response) override;

  grpc::Status RetireBlock(
      grpc::ServerContext* context,
      const retrovue::air::v1::RetireBlockRequest* request,
      retrovue::air::v1::RetireBlockResponse* response) override;

 private:
  std::mutex mu_;
  AirSession session_;
};

}  // namespace retrovue::air

#endif  // AIR_GRPC_SERVICE_HPP_
