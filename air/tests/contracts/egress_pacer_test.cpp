// AIR vNext — EgressPacer contract tests.
//
// Uses injected now/sleep functions so tests run instantly without real waits.

#include <gtest/gtest.h>

#include <cstdint>
#include <vector>

#include "egress_pacer.hpp"

namespace retrovue::air {
namespace {

// Fake clock that advances by whatever is sleeped + explicit nudges.
class FakeClock {
 public:
  int64_t Now() const { return now_us_; }
  void Sleep(int64_t us) {
    if (us > 0) {
      now_us_ += us;
      sleeps_.push_back(us);
    }
  }
  void Advance(int64_t us) { now_us_ += us; }

  const std::vector<int64_t>& Sleeps() const { return sleeps_; }
  int64_t SleepTotal() const {
    int64_t t = 0;
    for (auto s : sleeps_) t += s;
    return t;
  }

 private:
  int64_t now_us_ = 0;
  std::vector<int64_t> sleeps_;
};

EgressPacer MakePacer(FakeClock& clock) {
  return EgressPacer([&clock]() { return clock.Now(); },
                     [&clock](int64_t us) { clock.Sleep(us); });
}

TEST(EgressPacerTest, FirstWaitAnchorsAndDoesNotSleep) {
  FakeClock clock;
  EgressPacer pacer = MakePacer(clock);

  EXPECT_FALSE(pacer.Anchored());
  pacer.WaitFor(1'000'000);  // pts = 1,000,000 us
  EXPECT_TRUE(pacer.Anchored());
  EXPECT_EQ(clock.SleepTotal(), 0);
  EXPECT_EQ(pacer.TotalSleepUs(), 0);
}

TEST(EgressPacerTest, SubsequentWaitSleepsByPtsDelta) {
  FakeClock clock;
  EgressPacer pacer = MakePacer(clock);

  // Anchor at pts=0. wall_clock starts at 0.
  pacer.WaitFor(0);
  EXPECT_EQ(clock.Now(), 0);

  // No wall-clock time passes; next WaitFor at pts=33333 should sleep 33333us.
  pacer.WaitFor(33'333);
  EXPECT_EQ(clock.SleepTotal(), 33'333);
  EXPECT_EQ(clock.Now(), 33'333);
  EXPECT_EQ(pacer.TotalSleepUs(), 33'333);
  EXPECT_EQ(pacer.LateReleases(), 0);
}

TEST(EgressPacerTest, AheadOfScheduleSleepsPartial) {
  FakeClock clock;
  EgressPacer pacer = MakePacer(clock);

  pacer.WaitFor(0);  // anchor at (now=0, pts=0)

  // Simulate 20ms of compute elapsed.
  clock.Advance(20'000);

  // Target PTS is 33,333us. We're at 20,000. Should sleep ~13,333us.
  pacer.WaitFor(33'333);
  EXPECT_EQ(clock.SleepTotal(), 13'333);
  EXPECT_EQ(clock.Now(), 33'333);
  EXPECT_EQ(pacer.LateReleases(), 0);
}

TEST(EgressPacerTest, BehindScheduleDoesNotSleepAndCountsLate) {
  FakeClock clock;
  EgressPacer pacer = MakePacer(clock);

  pacer.WaitFor(0);  // anchor at (now=0, pts=0)

  // Simulate 50ms of compute elapsed (we're already behind the 33ms target).
  clock.Advance(50'000);

  // Target PTS is 33,333us. We're at 50,000. No sleep, count late.
  pacer.WaitFor(33'333);
  EXPECT_EQ(clock.SleepTotal(), 0);
  EXPECT_EQ(clock.Now(), 50'000);
  EXPECT_EQ(pacer.LateReleases(), 1);
  EXPECT_EQ(pacer.TotalSleepUs(), 0);
}

TEST(EgressPacerTest, ResetClearsAnchor) {
  FakeClock clock;
  EgressPacer pacer = MakePacer(clock);

  pacer.WaitFor(0);
  EXPECT_TRUE(pacer.Anchored());

  pacer.Reset();
  EXPECT_FALSE(pacer.Anchored());

  // Next WaitFor establishes a new anchor; no sleep even at distant PTS.
  clock.Advance(5'000'000);
  pacer.WaitFor(10'000'000);
  EXPECT_EQ(clock.SleepTotal(), 0);
  EXPECT_TRUE(pacer.Anchored());
}

TEST(EgressPacerTest, SequenceOfFramesPacesCumulatively) {
  FakeClock clock;
  EgressPacer pacer = MakePacer(clock);

  // 30fps cadence: frames at 0, 33333, 66667, 100000, 133333 us. No compute
  // overhead between frames. Each WaitFor should sleep exactly the PTS delta.
  const int64_t frame_period_us = 33'333;

  for (int i = 0; i < 5; ++i) {
    pacer.WaitFor(i * frame_period_us);
  }

  // First call anchors (no sleep). Four subsequent sleeps of frame_period_us.
  EXPECT_EQ(pacer.WaitsIssued(), 5);
  EXPECT_EQ(clock.Sleeps().size(), 4u);
  for (auto s : clock.Sleeps()) EXPECT_EQ(s, frame_period_us);
  EXPECT_EQ(clock.Now(), 4 * frame_period_us);
  EXPECT_EQ(pacer.LateReleases(), 0);
}

}  // namespace
}  // namespace retrovue::air
