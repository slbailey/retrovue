// Repository: Retrovue-playout
// Component: ObservabilityLawContractTests — LAW-OBS-001 through LAW-OBS-005
// Purpose: Contract tests for the Observability Parity Law.
//          Each test triggers the exact violation condition stated in the law
//          and asserts that Logger::ErrorStructured emits the expected
//          invariant-ID-tagged error.
// Contract: runtime/docs/contracts/laws/ObservabilityParityLaw.md §1–5
// Copyright (c) 2025 RetroVue

#include <gtest/gtest.h>
#include <string>
#include <vector>

#include "retrovue/util/Logger.hpp"
#include "retrovue/util/ObservabilityLogger.hpp"

using retrovue::util::Logger;
using retrovue::util::LogEntry;

// =============================================================================
// Log-capture fixture
// Captures both free-text error lines and structured LogEntry objects.
// =============================================================================
namespace {

class ObservabilityLawTest : public ::testing::Test {
 protected:
  void SetUp() override {
    captured_errors_.clear();
    captured_entries_.clear();
    captured_info_.clear();

    Logger::SetErrorSink([this](const std::string& line) {
      captured_errors_.push_back(line);
    });
    Logger::SetTestSink([this](const LogEntry& entry) {
      captured_entries_.push_back(entry);
    });
    Logger::SetInfoSink([this](const std::string& line) {
      captured_info_.push_back(line);
    });
  }

  void TearDown() override {
    Logger::SetErrorSink(nullptr);
    Logger::SetTestSink(nullptr);
    Logger::SetInfoSink(nullptr);
  }

  // Returns true if any captured error contains the given invariant violation tag.
  bool HasViolation(const std::string& invariant_id) const {
    for (const auto& line : captured_errors_) {
      if (line.find(invariant_id) != std::string::npos) return true;
    }
    return false;
  }

  // Returns true if any captured info line contains the given substring.
  bool HasInfoLine(const std::string& substr) const {
    for (const auto& line : captured_info_) {
      if (line.find(substr) != std::string::npos) return true;
    }
    return false;
  }

  // Returns true if any structured entry has the given invariant_id.
  bool HasStructuredViolation(const std::string& invariant_id) const {
    for (const auto& entry : captured_entries_) {
      if (entry.invariant_id == invariant_id) return true;
    }
    return false;
  }

  std::vector<std::string> captured_errors_;
  std::vector<LogEntry>    captured_entries_;
  std::vector<std::string> captured_info_;
};

}  // namespace

// =============================================================================
// LAW-OBS-001: Every Intent Must Be Observable
// Violation condition: an intent is issued without the rpc field (not named).
// We model "not observable" as calling LogIntentReceived with an empty rpc.
// =============================================================================

TEST_F(ObservabilityLawTest, LAW_OBS_001_IntentWithEmptyRpcIsViolation) {
  // Trigger: rpc is empty — intent is not named/observable
  retrovue::util::LogIntentReceived(
      /*correlation_id=*/"corr-001",
      /*rpc=*/"",          // <-- violation condition: empty rpc
      /*channel_id=*/1,
      /*receipt_time_ms=*/1700000000000LL,
      /*asset_path=*/{},
      /*start_frame=*/0,
      /*frame_count=*/0,
      /*rpc_requires_timing=*/false);

  EXPECT_TRUE(HasViolation("LAW-OBS-001-VIOLATED"))
      << "Expected LAW-OBS-001-VIOLATED when rpc is empty";
  EXPECT_TRUE(HasStructuredViolation("LAW-OBS-001-VIOLATED"));
}

TEST_F(ObservabilityLawTest, LAW_OBS_001_IntentWithNamedRpcIsCompliant) {
  // Compliant: rpc is named
  retrovue::util::LogIntentReceived(
      /*correlation_id=*/"corr-002",
      /*rpc=*/"LoadPreview",
      /*channel_id=*/1,
      /*receipt_time_ms=*/1700000001000LL,
      /*asset_path=*/"/media/ep1.mp4",
      /*start_frame=*/0,
      /*frame_count=*/1800,
      /*rpc_requires_timing=*/true);

  EXPECT_FALSE(HasViolation("LAW-OBS-001-VIOLATED"))
      << "No LAW-OBS-001 violation expected when rpc is named";
  EXPECT_TRUE(HasInfoLine("AIR-INTENT-RECEIVED"))
      << "AIR-INTENT-RECEIVED must be emitted";
  EXPECT_TRUE(HasInfoLine("correlation_id=corr-002"));
}

// =============================================================================
// LAW-OBS-002: Correlation ID Propagation
// Violation condition: correlation_id absent from AIR-INTENT-RECEIVED event.
// =============================================================================

TEST_F(ObservabilityLawTest, LAW_OBS_002_MissingCorrelationIdOnReceive) {
  // Trigger: correlation_id is empty
  retrovue::util::LogIntentReceived(
      /*correlation_id=*/"",  // <-- violation condition
      /*rpc=*/"LoadPreview",
      /*channel_id=*/1,
      /*receipt_time_ms=*/1700000002000LL,
      /*asset_path=*/"/media/ep2.mp4",
      /*start_frame=*/0,
      /*frame_count=*/900,
      /*rpc_requires_timing=*/true);

  EXPECT_TRUE(HasViolation("LAW-OBS-002-VIOLATED"))
      << "Expected LAW-OBS-002-VIOLATED when correlation_id is empty";
  EXPECT_TRUE(HasStructuredViolation("LAW-OBS-002-VIOLATED"));

  // The info event MUST still be emitted even when violation is flagged
  EXPECT_TRUE(HasInfoLine("AIR-INTENT-RECEIVED"))
      << "AIR-INTENT-RECEIVED must still be emitted even on violation";
}

TEST_F(ObservabilityLawTest, LAW_OBS_002_MissingCorrelationIdOnResponse) {
  // Trigger: response logged without correlation_id — also a LAW-OBS-002 gap
  // (the correlation_id does not appear in AIR-INTENT-RESPONSE either)
  retrovue::util::LogIntentResponse(
      /*correlation_id=*/"",  // <-- violation condition
      /*rpc=*/"LoadPreview",
      /*channel_id=*/1,
      /*success=*/true,
      /*result_code=*/"RESULT_CODE_OK",
      /*message=*/{},
      /*completion_time_ms=*/1700000002100LL,
      /*rpc_requires_timing=*/true);

  // LAW-OBS-003 covers the response side; this also contributes to LAW-OBS-002.
  EXPECT_TRUE(HasViolation("LAW-OBS-003-VIOLATED"))
      << "Expected LAW-OBS-003-VIOLATED (and thus LAW-OBS-002 gap) when "
         "correlation_id absent from response";
}

// =============================================================================
// LAW-OBS-003: Every Air Response Must Be Logged
// Violation condition: AIR-INTENT-RESPONSE logged without correlation_id or result_code.
// =============================================================================

TEST_F(ObservabilityLawTest, LAW_OBS_003_ResponseWithoutCorrelationIdIsViolation) {
  retrovue::util::LogIntentResponse(
      /*correlation_id=*/"",  // <-- violation
      /*rpc=*/"SwitchToLive",
      /*channel_id=*/2,
      /*success=*/true,
      /*result_code=*/"RESULT_CODE_OK",
      /*message=*/{},
      /*completion_time_ms=*/1700000003000LL,
      /*rpc_requires_timing=*/true);

  EXPECT_TRUE(HasViolation("LAW-OBS-003-VIOLATED"));
  EXPECT_TRUE(HasStructuredViolation("LAW-OBS-003-VIOLATED"));
}

TEST_F(ObservabilityLawTest, LAW_OBS_003_ResponseWithoutResultCodeIsViolation) {
  retrovue::util::LogIntentResponse(
      /*correlation_id=*/"corr-003",
      /*rpc=*/"SwitchToLive",
      /*channel_id=*/2,
      /*success=*/true,
      /*result_code=*/"",  // <-- violation
      /*message=*/{},
      /*completion_time_ms=*/1700000003500LL,
      /*rpc_requires_timing=*/true);

  EXPECT_TRUE(HasViolation("LAW-OBS-003-VIOLATED"));
}

TEST_F(ObservabilityLawTest, LAW_OBS_003_CompliantResponseIsLogged) {
  retrovue::util::LogIntentResponse(
      /*correlation_id=*/"corr-004",
      /*rpc=*/"LoadPreview",
      /*channel_id=*/1,
      /*success=*/true,
      /*result_code=*/"RESULT_CODE_OK",
      /*message=*/"preview loaded",
      /*completion_time_ms=*/1700000004000LL,
      /*rpc_requires_timing=*/true);

  EXPECT_FALSE(HasViolation("LAW-OBS-003-VIOLATED"));
  EXPECT_TRUE(HasInfoLine("AIR-INTENT-RESPONSE"));
  EXPECT_TRUE(HasInfoLine("correlation_id=corr-004"));
  EXPECT_TRUE(HasInfoLine("result_code=RESULT_CODE_OK"));
}

// =============================================================================
// LAW-OBS-004: Timing Evidence for RPC Operations
// Violation condition: receipt_time_ms or completion_time_ms absent from
//                      legacy preload RPC / legacy switch RPC events.
// =============================================================================

TEST_F(ObservabilityLawTest, LAW_OBS_004_MissingReceiptTimeOnPreload) {
  // Trigger: receipt_time_ms == 0 for a timed RPC (LoadPreview = legacy preload)
  retrovue::util::LogIntentReceived(
      /*correlation_id=*/"corr-005",
      /*rpc=*/"LoadPreview",
      /*channel_id=*/1,
      /*receipt_time_ms=*/0,  // <-- violation condition
      /*asset_path=*/"/media/ep3.mp4",
      /*start_frame=*/0,
      /*frame_count=*/1800,
      /*rpc_requires_timing=*/true);

  EXPECT_TRUE(HasViolation("LAW-OBS-004-VIOLATED"))
      << "Expected LAW-OBS-004-VIOLATED when receipt_time_ms is 0 for timed RPC";
  EXPECT_TRUE(HasStructuredViolation("LAW-OBS-004-VIOLATED"));
}

TEST_F(ObservabilityLawTest, LAW_OBS_004_MissingCompletionTimeOnSwitch) {
  // Trigger: completion_time_ms == 0 for SwitchToLive (legacy switch RPC)
  retrovue::util::LogIntentResponse(
      /*correlation_id=*/"corr-006",
      /*rpc=*/"SwitchToLive",
      /*channel_id=*/1,
      /*success=*/true,
      /*result_code=*/"RESULT_CODE_OK",
      /*message=*/{},
      /*completion_time_ms=*/0,  // <-- violation condition
      /*rpc_requires_timing=*/true);

  EXPECT_TRUE(HasViolation("LAW-OBS-004-VIOLATED"))
      << "Expected LAW-OBS-004-VIOLATED when completion_time_ms is 0 for timed RPC";
}

TEST_F(ObservabilityLawTest, LAW_OBS_004_TimingPresentIsCompliant) {
  retrovue::util::LogIntentReceived(
      "corr-007", "LoadPreview", 1, 1700000007000LL,
      "/media/ep4.mp4", 0, 1800, /*rpc_requires_timing=*/true);
  retrovue::util::LogIntentResponse(
      "corr-007", "LoadPreview", 1, true, "RESULT_CODE_OK", {},
      1700000007100LL, /*rpc_requires_timing=*/true);

  EXPECT_FALSE(HasViolation("LAW-OBS-004-VIOLATED"));
  EXPECT_TRUE(HasInfoLine("receipt_time_ms=1700000007000"));
  EXPECT_TRUE(HasInfoLine("completion_time_ms=1700000007100"));
}

// =============================================================================
// LAW-OBS-005: Hard-Stop Clamp Must Produce Explicit Logs
// Violation condition: clamp fires without channel_id, asset_path, or boundary_ms.
// =============================================================================

TEST_F(ObservabilityLawTest, LAW_OBS_005_ClampStartedWithoutRequiredFieldsIsViolation) {
  // Trigger: channel_id == 0, asset_path empty, boundary_ms == 0
  retrovue::util::LogClampStarted(
      /*correlation_id=*/"corr-008",
      /*channel_id=*/0,        // <-- violation
      /*asset_path=*/"",       // <-- violation
      /*boundary_ms=*/0);      // <-- violation

  EXPECT_TRUE(HasViolation("LAW-OBS-005-VIOLATED"))
      << "Expected LAW-OBS-005-VIOLATED when required clamp fields are absent";
  EXPECT_TRUE(HasStructuredViolation("LAW-OBS-005-VIOLATED"));
}

TEST_F(ObservabilityLawTest, LAW_OBS_005_ClampEndedWithoutRequiredFieldsIsViolation) {
  // Trigger: required fields absent from AIR-CLAMP-ENDED
  retrovue::util::LogClampEnded(
      /*channel_id=*/0,
      /*asset_path=*/"",
      /*boundary_ms=*/0);

  EXPECT_TRUE(HasViolation("LAW-OBS-005-VIOLATED"));
}

TEST_F(ObservabilityLawTest, LAW_OBS_005_CompleteClampSequenceIsCompliant) {
  // Compliant: all three events emitted with required fields
  retrovue::util::LogClampStarted(
      "corr-009", 1, "/media/ep5.mp4", 1700000009000LL,
      /*segment_correlation_id=*/"corr-008");

  retrovue::util::LogClampActive(
      1, "/media/ep5.mp4", 1700000009000LL, /*clamp_duration_ms=*/1200);

  retrovue::util::LogClampEnded(
      1, "/media/ep5.mp4", 1700000009000LL,
      /*next_correlation_id=*/"corr-010");

  EXPECT_FALSE(HasViolation("LAW-OBS-005-VIOLATED"));

  EXPECT_TRUE(HasInfoLine("AIR-CLAMP-STARTED"))
      << "AIR-CLAMP-STARTED must be emitted";
  EXPECT_TRUE(HasInfoLine("AIR-CLAMP-ACTIVE"))
      << "AIR-CLAMP-ACTIVE must be emitted";
  EXPECT_TRUE(HasInfoLine("AIR-CLAMP-ENDED"))
      << "AIR-CLAMP-ENDED must be emitted";

  // Verify required fields in each event
  EXPECT_TRUE(HasInfoLine("channel_id=1"));
  EXPECT_TRUE(HasInfoLine("asset_path=/media/ep5.mp4"));
  EXPECT_TRUE(HasInfoLine("boundary_ms=1700000009000"));
}

TEST_F(ObservabilityLawTest, LAW_OBS_005_ClampStartedWithOnlyMissingBoundaryIsViolation) {
  // boundary_ms == 0 alone is sufficient to trigger violation
  retrovue::util::LogClampStarted(
      "corr-011", /*channel_id=*/1, /*asset_path=*/"/media/ep6.mp4",
      /*boundary_ms=*/0);  // <-- violation

  EXPECT_TRUE(HasViolation("LAW-OBS-005-VIOLATED"));
}
