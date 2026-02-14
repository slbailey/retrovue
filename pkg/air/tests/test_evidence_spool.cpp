// Repository: RetroVue
// Component: AIR evidence spool unit tests
// Contract: pkg/air/docs/contracts/AirExecutionEvidenceSpoolContract_v0.1.md

#include <gtest/gtest.h>
#include <cerrno>
#include <chrono>
#include <fstream>
#include <sys/stat.h>
#include <thread>
#include <unistd.h>

#include "evidence/EvidenceSpool.hpp"
#include "evidence/EvidenceEmitter.hpp"

namespace retrovue::evidence {
namespace {

std::string MakeTempSpoolRoot() {
  std::string root = "/tmp/retrovue_evidence_spool_test_" + std::to_string(getpid());
  if (mkdir(root.c_str(), 0755) != 0 && errno != EEXIST) {
    root = "/tmp";  // fallback
  }
  return root;
}

void EnsureSpoolDirExists(const std::string& root, const std::string& channel_id) {
  std::string dir = root + "/" + channel_id;
  mkdir(dir.c_str(), 0755);  // ignore result (EEXIST ok)
}

// -----------------------------------------------------------------------------
// Append 5 events, restart spool, ReplayFrom(3) returns seq 4 and 5
// -----------------------------------------------------------------------------
TEST(EvidenceSpoolTest, AppendAndReplayFrom) {
  const std::string root = MakeTempSpoolRoot();
  const std::string channel_id = "test-channel";
  const std::string session_id = "PS-test-001";
  EnsureSpoolDirExists(root, channel_id);

  {
    auto spool = std::make_shared<EvidenceSpool>(channel_id, session_id, root);
    EvidenceEmitter emitter(channel_id, session_id, spool);

    BlockStartPayload p1;
    p1.block_id = "block-1";
    p1.swap_tick = 100;
    p1.actual_start_utc_ms = 1739448000000;
    p1.primed_success = true;
    emitter.EmitBlockStart(p1);
    emitter.EmitBlockStart(p1);  // 2
    emitter.EmitBlockStart(p1);   // 3
    emitter.EmitBlockStart(p1);   // 4
    emitter.EmitBlockStart(p1);   // 5

    // Allow writer thread to flush
    std::this_thread::sleep_for(std::chrono::milliseconds(400));
  }  // emitter and spool destroyed, writer thread joined

  // Restart: new spool object, same path
  EvidenceSpool spool2(channel_id, session_id, root);
  auto replayed = spool2.ReplayFrom(3);
  ASSERT_EQ(replayed.size(), 2u) << "ReplayFrom(3) should return sequences 4 and 5";
  EXPECT_EQ(replayed[0].sequence, 4u);
  EXPECT_EQ(replayed[1].sequence, 5u);
}

// -----------------------------------------------------------------------------
// Ack persistence: UpdateAck then GetLastAck
// -----------------------------------------------------------------------------
TEST(EvidenceSpoolTest, AckPersistence) {
  const std::string root = MakeTempSpoolRoot();
  const std::string channel_id = "ack-channel";
  const std::string session_id = "PS-ack-001";
  EnsureSpoolDirExists(root, channel_id);

  {
    EvidenceSpool spool(channel_id, session_id, root);
    EXPECT_EQ(spool.GetLastAck(), 0u);
    spool.UpdateAck(10);
    spool.UpdateAck(5);   // ignored (not strictly higher)
    spool.UpdateAck(20);
  }
  // New spool instance must see the persisted ack
  EvidenceSpool spool2(channel_id, session_id, root);
  EXPECT_EQ(spool2.GetLastAck(), 20u);
}

// -----------------------------------------------------------------------------
// Corrupt tail: final line incomplete → ignored, prior records intact
// -----------------------------------------------------------------------------
TEST(EvidenceSpoolTest, CorruptTailIgnored) {
  const std::string root = MakeTempSpoolRoot();
  const std::string channel_id = "corrupt-channel";
  const std::string session_id = "PS-corrupt-001";
  EnsureSpoolDirExists(root, channel_id);
  std::string spool_path;

  {
    EvidenceSpool spool(channel_id, session_id, root);
    spool_path = spool.SpoolPath();
    EvidenceFromAir msg;
    msg.schema_version = 1;
    msg.channel_id = channel_id;
    msg.playout_session_id = session_id;
    msg.sequence = 1;
    msg.event_uuid = "uuid-1";
    msg.emitted_utc = "2026-02-13T12:00:00.000Z";
    msg.payload_type = "BLOCK_START";
    msg.payload = "{}";
    spool.Append(msg);
    msg.sequence = 2;
    msg.event_uuid = "uuid-2";
    spool.Append(msg);
    std::this_thread::sleep_for(std::chrono::milliseconds(400));
  }  // spool destroyed, file closed

  // Append corrupt incomplete line to spool file
  std::ofstream append(spool_path, std::ios::app);
  append << "{\"schema_version\":1,\"incomplete";
  append.close();

  EvidenceSpool reader(channel_id, session_id, root);
  auto replayed = reader.ReplayFrom(0);
  // Contract SP-CRASH-002: corrupt final line ignored; prior records intact.
  ASSERT_EQ(replayed.size(), 2u);
  EXPECT_EQ(replayed[0].sequence, 1u);
  EXPECT_EQ(replayed[1].sequence, 2u);
}

// -----------------------------------------------------------------------------
// Sequence monotonicity: gap on append throws
// -----------------------------------------------------------------------------
TEST(EvidenceSpoolTest, SequenceGapThrows) {
  const std::string root = MakeTempSpoolRoot();
  const std::string channel_id = "gap-channel";
  const std::string session_id = "PS-gap-001";
  EnsureSpoolDirExists(root, channel_id);

  EvidenceSpool spool(channel_id, session_id, root);
  EvidenceFromAir msg;
  msg.schema_version = 1;
  msg.channel_id = channel_id;
  msg.playout_session_id = session_id;
  msg.sequence = 1;
  msg.event_uuid = "uuid-1";
  msg.emitted_utc = "2026-02-13T12:00:00.000Z";
  msg.payload_type = "BLOCK_START";
  msg.payload = "{}";
  spool.Append(msg);

  msg.sequence = 3;  // gap: expected 2
  EXPECT_THROW(spool.Append(msg), std::runtime_error);
}

// -----------------------------------------------------------------------------
// FromJsonLine / ToJsonLine round-trip
// -----------------------------------------------------------------------------
TEST(EvidenceSpoolTest, JsonRoundTrip) {
  EvidenceFromAir orig;
  orig.schema_version = 1;
  orig.channel_id = "ch";
  orig.playout_session_id = "PS-1";
  orig.sequence = 42;
  orig.event_uuid = "uuid-abc";
  orig.emitted_utc = "2026-02-13T12:00:00.000Z";
  orig.payload_type = "BLOCK_FENCE";
  orig.payload = "{\"block_id\":\"b1\"}";

  std::string line = orig.ToJsonLine();
  EXPECT_FALSE(line.empty());
  EXPECT_EQ(line.back(), '}');

  EvidenceFromAir parsed;
  ASSERT_TRUE(EvidenceFromAir::FromJsonLine(line, parsed));
  EXPECT_EQ(parsed.schema_version, orig.schema_version);
  EXPECT_EQ(parsed.channel_id, orig.channel_id);
  EXPECT_EQ(parsed.playout_session_id, orig.playout_session_id);
  EXPECT_EQ(parsed.sequence, orig.sequence);
  EXPECT_EQ(parsed.event_uuid, orig.event_uuid);
  EXPECT_EQ(parsed.emitted_utc, orig.emitted_utc);
  EXPECT_EQ(parsed.payload_type, orig.payload_type);
  EXPECT_EQ(parsed.payload, orig.payload);
}

// -----------------------------------------------------------------------------
// Disk cap enforcement (SP-RET-003): Append returns kSpoolFull when cap exceeded
// -----------------------------------------------------------------------------
TEST(EvidenceSpoolTest, DiskCapEnforced) {
  const std::string root = MakeTempSpoolRoot();
  const std::string channel_id = "cap-channel";
  const std::string session_id = "PS-cap-001";
  EnsureSpoolDirExists(root, channel_id);

  // Use a very small cap (512 bytes) so it fills quickly.
  constexpr size_t kSmallCap = 512;
  EvidenceSpool spool(channel_id, session_id, root, kSmallCap);

  EvidenceFromAir msg;
  msg.schema_version = 1;
  msg.channel_id = channel_id;
  msg.playout_session_id = session_id;
  msg.emitted_utc = "2026-02-13T12:00:00.000Z";
  msg.payload_type = "BLOCK_START";
  msg.payload = "{}";

  // Append records until the spool is full.
  int accepted = 0;
  int rejected = 0;
  for (uint64_t seq = 1; seq <= 100; ++seq) {
    msg.sequence = seq;
    msg.event_uuid = "uuid-" + std::to_string(seq);
    auto status = spool.Append(msg);
    if (status == AppendStatus::kOk) {
      ++accepted;
    } else {
      EXPECT_EQ(status, AppendStatus::kSpoolFull);
      ++rejected;
      break;  // First rejection is the signal.
    }
  }

  // Must have accepted at least 1 record before hitting the cap.
  EXPECT_GT(accepted, 0) << "Should accept at least one record before cap";
  // Must have rejected at least one — no silent drop.
  EXPECT_EQ(rejected, 1) << "Should reject once cap is exceeded";
  // Spool file size should not exceed the cap.
  EXPECT_LE(spool.CurrentSpoolBytes(), kSmallCap)
      << "Spool bytes must not exceed configured cap";
}

// -----------------------------------------------------------------------------
// Unlimited cap (default): Append always returns kOk
// -----------------------------------------------------------------------------
TEST(EvidenceSpoolTest, UnlimitedCapAllowsAll) {
  const std::string root = MakeTempSpoolRoot();
  const std::string channel_id = "unlimited-channel";
  const std::string session_id = "PS-unlimited-001";
  EnsureSpoolDirExists(root, channel_id);

  // Default cap (0 = unlimited).
  EvidenceSpool spool(channel_id, session_id, root);

  EvidenceFromAir msg;
  msg.schema_version = 1;
  msg.channel_id = channel_id;
  msg.playout_session_id = session_id;
  msg.emitted_utc = "2026-02-13T12:00:00.000Z";
  msg.payload_type = "BLOCK_START";
  msg.payload = "{}";

  for (uint64_t seq = 1; seq <= 20; ++seq) {
    msg.sequence = seq;
    msg.event_uuid = "uuid-" + std::to_string(seq);
    EXPECT_EQ(spool.Append(msg), AppendStatus::kOk);
  }
}

}  // namespace
}  // namespace retrovue::evidence
