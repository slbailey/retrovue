// Repository: Retrovue-playout
// Component: INV-TIME-AUTHORITY-SINGLE-SOURCE Contract Tests
// Purpose: Verify there is exactly one time authority in the system.
//          Audio is PCR master. Producer (TimelineController) is CT authority.
//          Mux derives PTS from producer CT plus offset. Mux does NOT maintain
//          local CT counters. CT is NOT reset on attach.
//
// Contract: docs/contracts/invariants/shared/INV-TIME-AUTHORITY-SINGLE-SOURCE.md
// Copyright (c) 2025 RetroVue

#include <gtest/gtest.h>
#include <cstdint>
#include <memory>
#include <string>

#include "retrovue/timing/MasterClock.h"
#include "retrovue/timing/TimelineController.h"

namespace {

class SingleSourceTestClock : public retrovue::timing::MasterClock {
 public:
  int64_t now_utc_us() const override { return now_us_; }
  double now_monotonic_s() const override { return now_us_ / 1'000'000.0; }
  int64_t scheduled_to_utc_us(int64_t pts_us) const override {
    return epoch_us_ + pts_us;
  }
  double drift_ppm() const override { return 0.0; }
  bool is_fake() const override { return true; }
  void set_epoch_utc_us(int64_t v) override { epoch_us_ = v; epoch_locked_ = true; }

  bool TrySetEpochOnce(int64_t v,
      EpochSetterRole role = EpochSetterRole::LIVE) override {
    if (role == EpochSetterRole::PREVIEW) return false;
    if (epoch_locked_) return false;
    epoch_us_ = v; epoch_locked_ = true;
    return true;
  }

  void ResetEpochForNewSession() override { epoch_locked_ = false; epoch_us_ = 0; }
  bool IsEpochLocked() const override { return epoch_locked_; }
  int64_t get_epoch_utc_us() const override { return epoch_us_; }
  void SetNow(int64_t v) { now_us_ = v; }

 private:
  int64_t now_us_ = 0;
  int64_t epoch_us_ = 0;
  bool epoch_locked_ = false;
};

}  // namespace

namespace retrovue::tests {

// INV-TIME-AUTHORITY-SINGLE-SOURCE: First TrySetEpochOnce succeeds; second is rejected.
TEST(InvTimeAuthoritySingleSource, Compliant_EpochSetOnce_SecondSetRejected) {
  SingleSourceTestClock clock;
  constexpr int64_t kEpoch = 1'700'000'000'000'000LL;

  EXPECT_TRUE(clock.TrySetEpochOnce(kEpoch, retrovue::timing::MasterClock::EpochSetterRole::LIVE))
      << "INV-TIME-AUTHORITY-SINGLE-SOURCE: First TrySetEpochOnce must succeed";
  EXPECT_TRUE(clock.IsEpochLocked());
  EXPECT_EQ(clock.get_epoch_utc_us(), kEpoch);

  // Second call from same role must fail — single source enforcement.
  EXPECT_FALSE(clock.TrySetEpochOnce(kEpoch + 1000, retrovue::timing::MasterClock::EpochSetterRole::LIVE))
      << "INV-TIME-AUTHORITY-SINGLE-SOURCE: Duplicate epoch set must be rejected";
  EXPECT_EQ(clock.get_epoch_utc_us(), kEpoch)
      << "INV-TIME-AUTHORITY-SINGLE-SOURCE: Epoch value must not change after rejection";
}

// INV-TIME-AUTHORITY-SINGLE-SOURCE: PREVIEW role is never permitted to set epoch.
TEST(InvTimeAuthoritySingleSource, Compliant_PreviewRoleAlwaysRejected) {
  SingleSourceTestClock clock;
  EXPECT_FALSE(clock.TrySetEpochOnce(1'700'000'000'000'000LL,
                                      retrovue::timing::MasterClock::EpochSetterRole::PREVIEW))
      << "INV-TIME-AUTHORITY-SINGLE-SOURCE: Producers (PREVIEW) must never set epoch";
  EXPECT_FALSE(clock.IsEpochLocked());
}

// INV-TIME-AUTHORITY-SINGLE-SOURCE: PTS is derived as epoch + offset (no local CT).
TEST(InvTimeAuthoritySingleSource, Compliant_PtsDerivedFromEpochPlusOffset) {
  SingleSourceTestClock clock;
  constexpr int64_t kEpoch = 1'700'000'000'000'000LL;
  clock.TrySetEpochOnce(kEpoch, retrovue::timing::MasterClock::EpochSetterRole::LIVE);

  EXPECT_EQ(clock.scheduled_to_utc_us(0), kEpoch)
      << "INV-TIME-AUTHORITY-SINGLE-SOURCE: PTS=0 maps to epoch (no independent CT)";
  EXPECT_EQ(clock.scheduled_to_utc_us(1'000'000), kEpoch + 1'000'000)
      << "INV-TIME-AUTHORITY-SINGLE-SOURCE: PTS=1s maps to epoch+1s (derivation, not reset)";
}

// INV-TIME-AUTHORITY-SINGLE-SOURCE: Session reset allows one new epoch per session.
TEST(InvTimeAuthoritySingleSource, Compliant_SessionResetAllowsNewEpoch) {
  SingleSourceTestClock clock;
  constexpr int64_t kE1 = 1'700'000'000'000'000LL;
  constexpr int64_t kE2 = 1'700'100'000'000'000LL;
  ASSERT_TRUE(clock.TrySetEpochOnce(kE1, retrovue::timing::MasterClock::EpochSetterRole::LIVE));

  clock.ResetEpochForNewSession();
  EXPECT_FALSE(clock.IsEpochLocked())
      << "INV-TIME-AUTHORITY-SINGLE-SOURCE: Epoch unlocked after session reset";
  EXPECT_TRUE(clock.TrySetEpochOnce(kE2, retrovue::timing::MasterClock::EpochSetterRole::LIVE))
      << "INV-TIME-AUTHORITY-SINGLE-SOURCE: New epoch allowed after session reset";
  EXPECT_EQ(clock.get_epoch_utc_us(), kE2);
}

}  // namespace retrovue::tests
