#include "grpc_pull_responder.hpp"

#include <grpcpp/grpcpp.h>

#include "air_control.grpc.pb.h"
#include "block.hpp"

namespace retrovue::air {
namespace {

ChannelCanonical BuildCanonicalFromProto(
    const retrovue::air::v1::ChannelCanonical& proto) {
  ChannelCanonical c{};
  c.video.width = proto.video_width();
  c.video.height = proto.video_height();
  c.video.frame_rate.num = proto.video_fps_num();
  c.video.frame_rate.den = proto.video_fps_den();
  c.video.pixel_format = PixelFormat::kYuv420p;
  c.audio.sample_rate = proto.audio_sample_rate();
  c.audio.channels = proto.audio_channels();
  return c;
}

Segment BuildSegmentFromProto(const retrovue::air::v1::Segment& p) {
  Segment s;
  s.segment_id = p.segment_id();
  s.asset_uri = p.asset_uri();
  s.asset_start_offset_ms = p.asset_start_offset_ms();
  s.duration_ms = p.duration_ms();
  s.segment_index = p.segment_index();
  return s;
}

Block BuildBlockFromProto(const retrovue::air::v1::Block& p) {
  Block b;
  b.block_id = p.block_id();
  b.start_utc_ms = p.start_utc_ms();
  b.end_utc_ms = p.end_utc_ms();
  if (p.has_canonical()) {
    b.canonical = BuildCanonicalFromProto(p.canonical());
  }
  b.segments.reserve(p.segments_size());
  for (const auto& seg_proto : p.segments()) {
    b.segments.push_back(BuildSegmentFromProto(seg_proto));
  }
  return b;
}

}  // namespace

PullResponder MakeGrpcPullResponder(std::shared_ptr<grpc::Channel> channel,
                                    int32_t channel_id) {
  auto stub =
      std::make_shared<retrovue::air::v1::CoreBlockSupply::Stub>(channel);
  return [stub, channel_id](
             const std::string& predecessor_id) -> std::optional<Block> {
    grpc::ClientContext ctx;
    retrovue::air::v1::GetSuccessorOfRequest req;
    req.set_channel_id(channel_id);
    req.set_predecessor_block_id(predecessor_id);
    retrovue::air::v1::GetSuccessorOfResponse resp;
    const auto status = stub->GetSuccessorOf(&ctx, req, &resp);
    if (!status.ok()) return std::nullopt;
    if (!resp.supplied()) return std::nullopt;
    return BuildBlockFromProto(resp.block());
  };
}

}  // namespace retrovue::air
