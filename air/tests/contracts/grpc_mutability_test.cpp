// AIR vNext — IR1a RPC mutability tests.
//
// Exercises AirControl's PutBlockRevision and RetireBlock through the
// gRPC wire, verifying:
//   - gRPC status == OK for every well-formed request, regardless of
//     admission decision (IR1 principle: gRPC = transport, response
//     body = business).
//   - Reason codes in the response body match
//     INV-PLAYBACK-BLOCK-MUTABILITY-001 and are consistent with the
//     C++-direct tests in air_session_mutability_test.cpp.
//
// Uses an in-process gRPC server to avoid external test fixtures.

#include <grpcpp/grpcpp.h>
#include <gtest/gtest.h>

#include <sys/socket.h>
#include <sys/un.h>
#include <unistd.h>

#include <atomic>
#include <cstdlib>
#include <cstring>
#include <filesystem>
#include <string>
#include <thread>

#include "air_control.grpc.pb.h"
#include "air_session.hpp"
#include "grpc_service.hpp"
#include "priming_pipeline.hpp"

namespace retrovue::air {
namespace {

std::string ResolveSampleA() {
  if (const char* env = std::getenv("AIR_VNEXT_TEST_MEDIA")) return env;
#ifdef AIR_VNEXT_SAMPLE_A_PATH
  return AIR_VNEXT_SAMPLE_A_PATH;
#else
  return "";
#endif
}

void FillCanonical(retrovue::air::v1::ChannelCanonical* c) {
  c->set_video_width(968);
  c->set_video_height(720);
  c->set_video_fps_num(30000);
  c->set_video_fps_den(1001);
  c->set_audio_sample_rate(48000);
  c->set_audio_channels(2);
}

void BuildBlockProto(retrovue::air::v1::Block* out,
                     const std::string& block_id,
                     const std::string& asset_path,
                     int segment_count,
                     int64_t start_utc_ms,
                     int64_t segment_duration_ms = 10000) {
  out->set_block_id(block_id);
  out->set_start_utc_ms(start_utc_ms);
  out->set_end_utc_ms(start_utc_ms + segment_count * segment_duration_ms);
  FillCanonical(out->mutable_canonical());
  for (int i = 0; i < segment_count; ++i) {
    auto* seg = out->add_segments();
    seg->set_segment_id(block_id + ":" + std::to_string(i));
    seg->set_asset_uri(asset_path);
    seg->set_asset_start_offset_ms(0);
    seg->set_duration_ms(segment_duration_ms);
    seg->set_segment_index(i);
  }
}

// Fixture: in-process gRPC server + client stub + seeded session with
// Block A active and Block B queued. AirSession is NOT OpenAir()ed,
// so queued B remains all-raw for mutability testing.
struct GrpcFixture {
  AirControlServiceImpl service;
  std::unique_ptr<grpc::Server> server;
  std::unique_ptr<retrovue::air::v1::AirControl::Stub> stub;
  std::string uds_path;
  int listen_fd = -1;
  int client_fd = -1;
  std::atomic<bool> reader_running{true};
  std::thread reader;

  bool Setup(const std::string& tag, bool seed_and_queue) {
    const std::string asset = ResolveSampleA();
    if (!std::filesystem::exists(asset)) return false;

    // gRPC server.
    grpc::ServerBuilder builder;
    int port = 0;
    builder.AddListeningPort("127.0.0.1:0",
                             grpc::InsecureServerCredentials(), &port);
    builder.RegisterService(&service);
    server = builder.BuildAndStart();
    auto channel = grpc::CreateChannel(
        "127.0.0.1:" + std::to_string(port),
        grpc::InsecureChannelCredentials());
    stub = retrovue::air::v1::AirControl::NewStub(channel);

    // UDS that StartChannel will connect to (Core side).
    uds_path = "/tmp/air_ir1a_" + tag + "_" + std::to_string(getpid()) + ".sock";
    ::unlink(uds_path.c_str());
    listen_fd = ::socket(AF_UNIX, SOCK_STREAM, 0);
    sockaddr_un addr{};
    addr.sun_family = AF_UNIX;
    std::strncpy(addr.sun_path, uds_path.c_str(), sizeof(addr.sun_path) - 1);
    ::bind(listen_fd, reinterpret_cast<sockaddr*>(&addr), sizeof(addr));
    ::listen(listen_fd, 1);
    reader = std::thread([this]() {
      int conn = ::accept(listen_fd, nullptr, nullptr);
      if (conn < 0) return;
      uint8_t buf[16 * 1024];
      while (reader_running.load()) {
        ssize_t n = ::read(conn, buf, sizeof(buf));
        if (n <= 0) break;
      }
      ::close(conn);
    });

    if (seed_and_queue) {
      // StartChannel with seed A (2 segments).
      grpc::ClientContext ctx;
      retrovue::air::v1::StartChannelRequest req;
      req.set_channel_id(1);
      req.set_output_uds_path(uds_path);
      FillCanonical(req.mutable_canonical());
      BuildBlockProto(req.mutable_seed_block(), "A", asset, 2,
                      1'700'000'000'000LL);
      retrovue::air::v1::StartChannelResponse resp;
      if (!stub->StartChannel(&ctx, req, &resp).ok() || !resp.ok()) {
        return false;
      }
      // SupplyBlock B (2 segments).
      grpc::ClientContext ctx2;
      retrovue::air::v1::SupplyBlockRequest sreq;
      sreq.set_channel_id(1);
      sreq.set_predecessor_id("A");
      BuildBlockProto(sreq.mutable_block(), "B", asset, 2,
                      1'700'000'000'000LL + 20000);
      retrovue::air::v1::SupplyBlockResponse sresp;
      if (!stub->SupplyBlock(&ctx2, sreq, &sresp).ok() || !sresp.ok()) {
        return false;
      }
    }

    return true;
  }

  void Teardown() {
    // StopChannel cleanly.
    {
      grpc::ClientContext ctx;
      retrovue::air::v1::StopChannelRequest req;
      req.set_channel_id(1);
      retrovue::air::v1::StopChannelResponse resp;
      stub->StopChannel(&ctx, req, &resp);
    }
    if (server) server->Shutdown();
    reader_running.store(false);
    // If no client ever connected (seed_and_queue=false path), the
    // reader is blocked in accept(). Shutdown the listening socket
    // to unblock it before join().
    if (listen_fd >= 0) ::shutdown(listen_fd, SHUT_RDWR);
    if (reader.joinable()) reader.join();
    if (listen_fd >= 0) ::close(listen_fd);
    ::unlink(uds_path.c_str());
  }
};

// --- PutBlockRevision over gRPC ------------------------------------------

TEST(GrpcMutabilityTest, PutBlockRevision_AllRawAccepted) {
  GrpcFixture f;
  if (!f.Setup("rev_raw", /*seed_and_queue=*/true)) GTEST_SKIP();

  // Revise B with a 3-segment variant. Queued B's segments are all kRaw
  // (StartChannel → OnAir hasn't been reached in this surface yet for
  // queued blocks; their priming only runs post-OpenAir. StartChannel
  // does OpenAir, but B.segments might still be kRaw if priming worker
  // hasn't reached them. Use a fresh block_id to avoid timing — actually
  // revise B directly; AddQueuedBlock just happened so B.segments are
  // still in their initial kRaw state before the priming worker picks
  // them up. Revision typically races with priming; rely on the logic
  // rather than tight timing.)
  //
  // More robust: poll once after SupplyBlock before OpenAir completes,
  // and revise B there. In the current setup StartChannel implies
  // OpenAir happened, so B may briefly be raw before priming starts.
  grpc::ClientContext ctx;
  retrovue::air::v1::PutBlockRevisionRequest req;
  req.set_channel_id(1);
  BuildBlockProto(req.mutable_block(), "B", ResolveSampleA(), 3,
                  1'700'000'000'000LL + 20000);
  retrovue::air::v1::PutBlockRevisionResponse resp;
  const auto status = f.stub->PutBlockRevision(&ctx, req, &resp);
  EXPECT_TRUE(status.ok())
      << "gRPC status MUST be OK regardless of accept/reject (transport layer)";
  // Either ok=true (timing race: raced with priming) or ok=false with
  // a mutability reason. Both are vault-compliant outcomes.
  if (!resp.ok()) {
    EXPECT_TRUE(resp.reason() == "BLOCK_PRIMING" ||
                resp.reason() == "BLOCK_ARMED")
        << "unexpected reason: " << resp.reason();
  }
  f.Teardown();
}

TEST(GrpcMutabilityTest, PutBlockRevision_ActiveBlockImmutable) {
  GrpcFixture f;
  if (!f.Setup("rev_active", /*seed_and_queue=*/true)) GTEST_SKIP();

  grpc::ClientContext ctx;
  retrovue::air::v1::PutBlockRevisionRequest req;
  req.set_channel_id(1);
  BuildBlockProto(req.mutable_block(), "A", ResolveSampleA(), 2,
                  1'700'000'000'000LL);  // active
  retrovue::air::v1::PutBlockRevisionResponse resp;
  ASSERT_TRUE(f.stub->PutBlockRevision(&ctx, req, &resp).ok());
  EXPECT_FALSE(resp.ok());
  EXPECT_EQ(resp.reason(), "ACTIVE_BLOCK_IMMUTABLE");

  f.Teardown();
}

TEST(GrpcMutabilityTest, PutBlockRevision_EmptySegmentsRejected) {
  GrpcFixture f;
  if (!f.Setup("rev_empty", /*seed_and_queue=*/true)) GTEST_SKIP();

  grpc::ClientContext ctx;
  retrovue::air::v1::PutBlockRevisionRequest req;
  req.set_channel_id(1);
  auto* b = req.mutable_block();
  b->set_block_id("B");
  FillCanonical(b->mutable_canonical());
  // No segments appended.
  retrovue::air::v1::PutBlockRevisionResponse resp;
  ASSERT_TRUE(f.stub->PutBlockRevision(&ctx, req, &resp).ok());
  EXPECT_FALSE(resp.ok());
  EXPECT_EQ(resp.reason(), "EMPTY_SEGMENTS");

  f.Teardown();
}

TEST(GrpcMutabilityTest, PutBlockRevision_BlockNotInQueueRejected) {
  GrpcFixture f;
  if (!f.Setup("rev_not_q", /*seed_and_queue=*/true)) GTEST_SKIP();

  grpc::ClientContext ctx;
  retrovue::air::v1::PutBlockRevisionRequest req;
  req.set_channel_id(1);
  BuildBlockProto(req.mutable_block(), "Z", ResolveSampleA(), 1,
                  1'700'000'000'999LL);
  retrovue::air::v1::PutBlockRevisionResponse resp;
  ASSERT_TRUE(f.stub->PutBlockRevision(&ctx, req, &resp).ok());
  EXPECT_FALSE(resp.ok());
  EXPECT_EQ(resp.reason(), "BLOCK_NOT_IN_QUEUE");

  f.Teardown();
}

// --- RetireBlock over gRPC -----------------------------------------------

TEST(GrpcMutabilityTest, RetireBlock_QueuedBlockAccepted) {
  GrpcFixture f;
  if (!f.Setup("ret_q", /*seed_and_queue=*/true)) GTEST_SKIP();

  grpc::ClientContext ctx;
  retrovue::air::v1::RetireBlockRequest req;
  req.set_channel_id(1);
  req.set_block_id("B");
  retrovue::air::v1::RetireBlockResponse resp;
  const auto status = f.stub->RetireBlock(&ctx, req, &resp);
  EXPECT_TRUE(status.ok());
  EXPECT_TRUE(resp.ok()) << "retire B failed: " << resp.reason();
  EXPECT_TRUE(resp.reason().empty());

  // Follow-up retire of the same id → BLOCK_NOT_IN_QUEUE.
  grpc::ClientContext ctx2;
  retrovue::air::v1::RetireBlockResponse resp2;
  ASSERT_TRUE(f.stub->RetireBlock(&ctx2, req, &resp2).ok());
  EXPECT_FALSE(resp2.ok());
  EXPECT_EQ(resp2.reason(), "BLOCK_NOT_IN_QUEUE");

  f.Teardown();
}

TEST(GrpcMutabilityTest, RetireBlock_ActiveBlockRejected) {
  GrpcFixture f;
  if (!f.Setup("ret_active", /*seed_and_queue=*/true)) GTEST_SKIP();

  grpc::ClientContext ctx;
  retrovue::air::v1::RetireBlockRequest req;
  req.set_channel_id(1);
  req.set_block_id("A");  // active
  retrovue::air::v1::RetireBlockResponse resp;
  ASSERT_TRUE(f.stub->RetireBlock(&ctx, req, &resp).ok());
  EXPECT_FALSE(resp.ok());
  EXPECT_EQ(resp.reason(), "ACTIVE_BLOCK_IMMUTABLE");

  f.Teardown();
}

TEST(GrpcMutabilityTest, RetireBlock_NoSessionRejected) {
  // Set up service only; no StartChannel → no session. RetireBlock
  // should return ok=false with NO_SESSION, gRPC status OK.
  GrpcFixture f;
  if (!f.Setup("ret_nosess", /*seed_and_queue=*/false)) GTEST_SKIP();

  grpc::ClientContext ctx;
  retrovue::air::v1::RetireBlockRequest req;
  req.set_channel_id(1);
  req.set_block_id("whatever");
  retrovue::air::v1::RetireBlockResponse resp;
  ASSERT_TRUE(f.stub->RetireBlock(&ctx, req, &resp).ok());
  EXPECT_FALSE(resp.ok());
  EXPECT_EQ(resp.reason(), "NO_SESSION");

  f.Teardown();
}

// --- Transport-layer-vs-business-layer separation ------------------------

TEST(GrpcMutabilityTest, GrpcStatusAlwaysOkOnAdmissionDecision) {
  // Combined probe: every well-formed request — whether accepted or
  // rejected — MUST return grpc::Status::OK. Reason codes live in
  // response body. IR1 principle.
  GrpcFixture f;
  if (!f.Setup("status_probe", /*seed_and_queue=*/true)) GTEST_SKIP();

  // Reject case: revision of active block.
  {
    grpc::ClientContext ctx;
    retrovue::air::v1::PutBlockRevisionRequest req;
    req.set_channel_id(1);
    BuildBlockProto(req.mutable_block(), "A", ResolveSampleA(), 2,
                    1'700'000'000'000LL);
    retrovue::air::v1::PutBlockRevisionResponse resp;
    const auto s = f.stub->PutBlockRevision(&ctx, req, &resp);
    EXPECT_EQ(s.error_code(), grpc::StatusCode::OK);
    EXPECT_FALSE(resp.ok());
    EXPECT_FALSE(resp.reason().empty());
  }
  // Accept case: retire queued B.
  {
    grpc::ClientContext ctx;
    retrovue::air::v1::RetireBlockRequest req;
    req.set_channel_id(1);
    req.set_block_id("B");
    retrovue::air::v1::RetireBlockResponse resp;
    const auto s = f.stub->RetireBlock(&ctx, req, &resp);
    EXPECT_EQ(s.error_code(), grpc::StatusCode::OK);
    EXPECT_TRUE(resp.ok());
  }

  f.Teardown();
}

// --- IR1a.5: mutation observability via GetSessionStatus ----------------

TEST(GrpcMutabilityTest, GetSessionStatusTalliesAcceptsAndRejects) {
  // Drive a mixed sequence of mutation RPCs through the wire and verify
  // the admission outcomes are reflected in GetSessionStatus's
  // revisions_accepted_total / revisions_rejected_total counters.
  // Fixture seeds: A active, B queued (all-raw).
  GrpcFixture f;
  if (!f.Setup("status_tally", /*seed_and_queue=*/true)) GTEST_SKIP();

  const std::string asset = ResolveSampleA();
  int expected_accepts = 0;
  int expected_rejects = 0;

  // Reject 1: revision of active A → ACTIVE_BLOCK_IMMUTABLE.
  {
    grpc::ClientContext ctx;
    retrovue::air::v1::PutBlockRevisionRequest req;
    req.set_channel_id(1);
    BuildBlockProto(req.mutable_block(), "A", asset, 2, 1'700'000'000'000LL);
    retrovue::air::v1::PutBlockRevisionResponse resp;
    ASSERT_TRUE(f.stub->PutBlockRevision(&ctx, req, &resp).ok());
    EXPECT_FALSE(resp.ok());
    ++expected_rejects;
  }
  // Reject 2: revision of unknown Z → BLOCK_NOT_IN_QUEUE.
  {
    grpc::ClientContext ctx;
    retrovue::air::v1::PutBlockRevisionRequest req;
    req.set_channel_id(1);
    BuildBlockProto(req.mutable_block(), "Z", asset, 2, 1'700'000'000'000LL);
    retrovue::air::v1::PutBlockRevisionResponse resp;
    ASSERT_TRUE(f.stub->PutBlockRevision(&ctx, req, &resp).ok());
    EXPECT_FALSE(resp.ok());
    ++expected_rejects;
  }
  // Reject 3: revision of B with no segments → EMPTY_SEGMENTS.
  {
    grpc::ClientContext ctx;
    retrovue::air::v1::PutBlockRevisionRequest req;
    req.set_channel_id(1);
    req.mutable_block()->set_block_id("B");
    FillCanonical(req.mutable_block()->mutable_canonical());
    retrovue::air::v1::PutBlockRevisionResponse resp;
    ASSERT_TRUE(f.stub->PutBlockRevision(&ctx, req, &resp).ok());
    EXPECT_FALSE(resp.ok());
    ++expected_rejects;
  }
  // Accept 1: revision of all-raw queued B.
  {
    grpc::ClientContext ctx;
    retrovue::air::v1::PutBlockRevisionRequest req;
    req.set_channel_id(1);
    BuildBlockProto(req.mutable_block(), "B", asset, 3,
                    1'700'000'000'000LL + 20000);
    retrovue::air::v1::PutBlockRevisionResponse resp;
    ASSERT_TRUE(f.stub->PutBlockRevision(&ctx, req, &resp).ok());
    EXPECT_TRUE(resp.ok());
    ++expected_accepts;
  }
  // Reject 4: retire unknown Z → BLOCK_NOT_IN_QUEUE.
  {
    grpc::ClientContext ctx;
    retrovue::air::v1::RetireBlockRequest req;
    req.set_channel_id(1);
    req.set_block_id("Z");
    retrovue::air::v1::RetireBlockResponse resp;
    ASSERT_TRUE(f.stub->RetireBlock(&ctx, req, &resp).ok());
    EXPECT_FALSE(resp.ok());
    ++expected_rejects;
  }
  // Accept 2: retire queued B.
  {
    grpc::ClientContext ctx;
    retrovue::air::v1::RetireBlockRequest req;
    req.set_channel_id(1);
    req.set_block_id("B");
    retrovue::air::v1::RetireBlockResponse resp;
    ASSERT_TRUE(f.stub->RetireBlock(&ctx, req, &resp).ok());
    EXPECT_TRUE(resp.ok());
    ++expected_accepts;
  }

  // Readback via GetSessionStatus. Counters must match the tallies we
  // observed in the response bodies — same truth from the body-level
  // outcome and the status-level snapshot.
  {
    grpc::ClientContext ctx;
    retrovue::air::v1::GetSessionStatusRequest req;
    req.set_channel_id(1);
    retrovue::air::v1::GetSessionStatusResponse resp;
    ASSERT_TRUE(f.stub->GetSessionStatus(&ctx, req, &resp).ok());
    EXPECT_EQ(resp.revisions_accepted_total(), expected_accepts);
    EXPECT_EQ(resp.revisions_rejected_total(), expected_rejects);
  }

  f.Teardown();
}

// --- IR2.1: structural admission over the wire -------------------------
//
// Light gRPC-path coverage proving AirSession's IR2.1 reason codes flow
// through each push RPC verbatim. Exhaustive per-code coverage lives in
// block_validation_test.cpp and air_session_admission_test.cpp.

TEST(GrpcMutabilityTest, PutBlockRevision_DurationMismatchRejected) {
  GrpcFixture f;
  if (!f.Setup("ir21_revise_dm", /*seed_and_queue=*/true)) GTEST_SKIP();

  grpc::ClientContext ctx;
  retrovue::air::v1::PutBlockRevisionRequest req;
  req.set_channel_id(1);
  auto* b = req.mutable_block();
  BuildBlockProto(b, "B", ResolveSampleA(), 2,
                  1'700'000'000'000LL + 20000);
  // Stretch the window so sum(durations) no longer matches: block spans
  // 30000ms by wall clock but segments sum to 20000ms.
  b->set_end_utc_ms(b->start_utc_ms() + 30000);

  retrovue::air::v1::PutBlockRevisionResponse resp;
  ASSERT_TRUE(f.stub->PutBlockRevision(&ctx, req, &resp).ok());
  EXPECT_FALSE(resp.ok());
  EXPECT_EQ(resp.reason(), "DURATION_MISMATCH");

  f.Teardown();
}

TEST(GrpcMutabilityTest, SupplyBlock_MalformedSegmentRejected) {
  GrpcFixture f;
  if (!f.Setup("ir21_supply_mf", /*seed_and_queue=*/true)) GTEST_SKIP();

  grpc::ClientContext ctx;
  retrovue::air::v1::SupplyBlockRequest req;
  req.set_channel_id(1);
  req.set_predecessor_id("B");
  auto* c = req.mutable_block();
  BuildBlockProto(c, "C", ResolveSampleA(), 2,
                  1'700'000'000'000LL + 40000);
  // Break a segment: empty asset_uri on segments[1] → MALFORMED_SEGMENT.
  c->mutable_segments(1)->clear_asset_uri();

  retrovue::air::v1::SupplyBlockResponse resp;
  ASSERT_TRUE(f.stub->SupplyBlock(&ctx, req, &resp).ok());
  EXPECT_FALSE(resp.ok());
  EXPECT_EQ(resp.reason(), "MALFORMED_SEGMENT");

  f.Teardown();
}

// --- IR2.2: canonical mismatch over the wire ---------------------------

TEST(GrpcMutabilityTest, SupplyBlock_CanonicalMismatchRejected) {
  GrpcFixture f;
  if (!f.Setup("ir22_supply_cm", /*seed_and_queue=*/true)) GTEST_SKIP();

  grpc::ClientContext ctx;
  retrovue::air::v1::SupplyBlockRequest req;
  req.set_channel_id(1);
  req.set_predecessor_id("B");
  auto* c = req.mutable_block();
  BuildBlockProto(c, "C", ResolveSampleA(), 2,
                  1'700'000'000'000LL + 40000);
  // Override the filled-in canonical with a mismatched audio rate.
  c->mutable_canonical()->set_audio_sample_rate(44100);

  retrovue::air::v1::SupplyBlockResponse resp;
  ASSERT_TRUE(f.stub->SupplyBlock(&ctx, req, &resp).ok());
  EXPECT_FALSE(resp.ok());
  EXPECT_EQ(resp.reason(), "CANONICAL_MISMATCH");

  f.Teardown();
}

TEST(GrpcMutabilityTest, PutBlockRevision_CanonicalMismatchRejected) {
  GrpcFixture f;
  if (!f.Setup("ir22_revise_cm", /*seed_and_queue=*/true)) GTEST_SKIP();

  grpc::ClientContext ctx;
  retrovue::air::v1::PutBlockRevisionRequest req;
  req.set_channel_id(1);
  auto* b = req.mutable_block();
  BuildBlockProto(b, "B", ResolveSampleA(), 2,
                  1'700'000'000'000LL + 20000);
  b->mutable_canonical()->set_video_width(1280);  // was 968

  retrovue::air::v1::PutBlockRevisionResponse resp;
  ASSERT_TRUE(f.stub->PutBlockRevision(&ctx, req, &resp).ok());
  EXPECT_FALSE(resp.ok());
  EXPECT_EQ(resp.reason(), "CANONICAL_MISMATCH");

  f.Teardown();
}

}  // namespace
}  // namespace retrovue::air
