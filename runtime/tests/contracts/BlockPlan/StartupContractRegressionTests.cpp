// Repository: Retrovue-playout
// Component: Startup contract regression tests
// Purpose: Prove AIR rejects legacy/invalid startup inputs and enforces BlockPlan startup.

#include <gtest/gtest.h>

#include <chrono>
#include <cstdio>
#include <cstring>
#include <memory>
#include <string>

#include <sys/socket.h>
#include <sys/un.h>
#include <unistd.h>

#include "playout.pb.h"
#include "playout.grpc.pb.h"
#include "playout_service.h"
#include "retrovue/runtime/PlayoutEngine.h"
#include "retrovue/runtime/PlayoutInterface.h"
#include "retrovue/telemetry/MetricsExporter.h"
#include "retrovue/timing/MasterClock.h"

namespace {

constexpr const char* kProgramFormatJson =
    R"({"video":{"width":1920,"height":1080,"frame_rate":"30/1"},"audio":{"sample_rate":48000,"channels":2}})";

class ScopedUnixListener {
 public:
  explicit ScopedUnixListener(const std::string& path) : path_(path) {
    fd_ = ::socket(AF_UNIX, SOCK_STREAM, 0);
    if (fd_ < 0) {
      ADD_FAILURE() << "socket(AF_UNIX) failed: " << std::strerror(errno);
      return;
    }

    ::unlink(path_.c_str());

    struct sockaddr_un addr;
    std::memset(&addr, 0, sizeof(addr));
    addr.sun_family = AF_UNIX;
    std::snprintf(addr.sun_path, sizeof(addr.sun_path), "%s", path_.c_str());

    if (::bind(fd_, reinterpret_cast<struct sockaddr*>(&addr), sizeof(addr)) != 0) {
      ADD_FAILURE() << "bind() failed: " << std::strerror(errno);
      ::close(fd_);
      fd_ = -1;
      return;
    }
    if (::listen(fd_, 1) != 0) {
      ADD_FAILURE() << "listen() failed: " << std::strerror(errno);
      ::close(fd_);
      fd_ = -1;
    }
  }

  ~ScopedUnixListener() {
    if (fd_ >= 0) {
      ::close(fd_);
    }
    ::unlink(path_.c_str());
  }

  const std::string& path() const { return path_; }

 private:
  int fd_{-1};
  std::string path_;
};

static retrovue::playout::BlockPlan MakeTwoSegmentBlock(
    const std::string& block_id,
    int64_t start_utc_ms,
    int64_t seg0_ms,
    int64_t seg1_ms) {
  retrovue::playout::BlockPlan block;
  block.set_block_id(block_id);
  block.set_channel_id(201);
  block.set_start_utc_ms(start_utc_ms);
  block.set_end_utc_ms(start_utc_ms + seg0_ms + seg1_ms);

  auto* seg0 = block.add_segments();
  seg0->set_segment_index(0);
  seg0->set_asset_uri("/media/a.mp4");
  seg0->set_asset_start_offset_ms(0);
  seg0->set_segment_duration_ms(seg0_ms);

  auto* seg1 = block.add_segments();
  seg1->set_segment_index(1);
  seg1->set_asset_uri("/media/b.mp4");
  seg1->set_asset_start_offset_ms(0);
  seg1->set_segment_duration_ms(seg1_ms);
  return block;
}

static retrovue::playout::BlockPlan MakeInvalidTimingBlock(const std::string& block_id) {
  retrovue::playout::BlockPlan block;
  block.set_block_id(block_id);
  block.set_channel_id(201);
  block.set_start_utc_ms(1'700'000'000'000);
  block.set_end_utc_ms(0);  // invalid / missing effective block timing

  auto* seg = block.add_segments();
  seg->set_segment_index(0);
  seg->set_asset_uri("/media/only.mp4");
  seg->set_asset_start_offset_ms(0);
  seg->set_segment_duration_ms(30'000);
  return block;
}

static std::shared_ptr<retrovue::playout::PlayoutControlImpl> MakeService() {
  auto metrics = std::make_shared<retrovue::telemetry::MetricsExporter>(0);
  auto clock = retrovue::timing::MakeSystemMasterClock(0, 0.0);
  auto engine = std::make_shared<retrovue::runtime::PlayoutEngine>(metrics, clock, false);
  auto interface = std::make_shared<retrovue::runtime::PlayoutInterface>(engine);
  return std::make_shared<retrovue::playout::PlayoutControlImpl>(interface, false);
}

static void AttachStreamOrAssert(
    retrovue::playout::PlayoutControlImpl* service,
    int32_t channel_id,
    const std::string& socket_path) {
  grpc::ServerContext ctx;
  retrovue::playout::AttachStreamRequest req;
  retrovue::playout::AttachStreamResponse resp;
  req.set_channel_id(channel_id);
  req.set_transport(retrovue::playout::STREAM_TRANSPORT_UNIX_DOMAIN_SOCKET);
  req.set_endpoint(socket_path);
  req.set_replace_existing(true);
  ASSERT_TRUE(service->AttachStream(&ctx, &req, &resp).ok());
  ASSERT_TRUE(resp.success()) << resp.message();
}

}  // namespace

TEST(StartupContractRegressionTests, StartBlockPlanSessionRejectsMissingJoinUtcMs) {
  auto service = MakeService();
  const int32_t channel_id = 201;
  ScopedUnixListener uds("/tmp/retrovue_startup_contract_missing_join.sock");
  AttachStreamOrAssert(service.get(), channel_id, uds.path());

  grpc::ServerContext ctx;
  retrovue::playout::StartBlockPlanSessionRequest req;
  retrovue::playout::StartBlockPlanSessionResponse resp;
  req.set_channel_id(channel_id);
  *req.mutable_block_a() = MakeTwoSegmentBlock("B0", 1'700'000'000'000, 15'000, 15'000);
  *req.mutable_block_b() = MakeTwoSegmentBlock("B1", 1'700'000'030'000, 15'000, 15'000);
  req.set_join_utc_ms(0);
  req.set_program_format_json(kProgramFormatJson);

  ASSERT_TRUE(service->StartBlockPlanSession(&ctx, &req, &resp).ok());
  EXPECT_FALSE(resp.success());
  EXPECT_EQ(resp.result_code(), retrovue::playout::BLOCKPLAN_RESULT_INVALID_BLOCK);
  EXPECT_NE(resp.message().find("join_utc_ms is required"), std::string::npos);
}

TEST(StartupContractRegressionTests, StartBlockPlanSessionRejectsMissingBlockTiming) {
  auto service = MakeService();
  const int32_t channel_id = 201;
  ScopedUnixListener uds("/tmp/retrovue_startup_contract_missing_timing.sock");
  AttachStreamOrAssert(service.get(), channel_id, uds.path());

  grpc::ServerContext ctx;
  retrovue::playout::StartBlockPlanSessionRequest req;
  retrovue::playout::StartBlockPlanSessionResponse resp;
  req.set_channel_id(channel_id);
  *req.mutable_block_a() = MakeInvalidTimingBlock("B0");
  *req.mutable_block_b() = MakeTwoSegmentBlock("B1", 1'700'000'030'000, 15'000, 15'000);
  req.set_join_utc_ms(1'700'000'000'000);
  req.set_program_format_json(kProgramFormatJson);

  ASSERT_TRUE(service->StartBlockPlanSession(&ctx, &req, &resp).ok());
  EXPECT_FALSE(resp.success());
  EXPECT_EQ(resp.result_code(), retrovue::playout::BLOCKPLAN_RESULT_INVALID_BLOCK);
  EXPECT_NE(resp.message().find("end_utc_ms must be greater than start_utc_ms"), std::string::npos);
}

TEST(StartupContractRegressionTests, LoadPreviewRejectsLegacySegmentOnlyPlaybackAttempt) {
  auto service = MakeService();

  grpc::ServerContext ctx;
  retrovue::playout::LoadPreviewRequest req;
  retrovue::playout::LoadPreviewResponse resp;
  req.set_channel_id(201);
  req.set_asset_path("/media/legacy.mp4");
  req.set_start_frame(0);
  req.set_frame_count(900);
  req.set_fps_numerator(30);
  req.set_fps_denominator(1);

  ASSERT_TRUE(service->LoadPreview(&ctx, &req, &resp).ok());
  EXPECT_FALSE(resp.success());
  EXPECT_EQ(resp.result_code(), retrovue::playout::RESULT_CODE_PROTOCOL_VIOLATION);
  EXPECT_NE(resp.message().find("segment-only playback attempt is forbidden"), std::string::npos);
}
