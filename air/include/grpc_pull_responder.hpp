// AIR vNext — grpc-backed PullResponder factory (IR1b).
//
// Produces a PullResponder (see air_session.hpp) that dispatches each
// call to CoreBlockSupply::GetSuccessorOf over a grpc::Channel. AIR is
// the client of this RPC; Core hosts the service.
//
// Semantics: supplied=false and transport-layer failures both produce
// std::nullopt so AirSession's pull worker backs off and retries per
// INV-PULL-SINGLE-OUTSTANDING-001. The factory does not interpret any
// admission reason codes — none exist on this RPC at IR1b.

#ifndef AIR_GRPC_PULL_RESPONDER_HPP_
#define AIR_GRPC_PULL_RESPONDER_HPP_

#include <cstdint>
#include <memory>

#include "air_session.hpp"

namespace grpc {
class Channel;
}

namespace retrovue::air {

PullResponder MakeGrpcPullResponder(std::shared_ptr<grpc::Channel> channel,
                                    int32_t channel_id);

}  // namespace retrovue::air

#endif  // AIR_GRPC_PULL_RESPONDER_HPP_
