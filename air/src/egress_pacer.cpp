// AIR vNext — EgressPacer implementation.

#include "egress_pacer.hpp"

#include <chrono>
#include <thread>

namespace retrovue::air {

namespace {

int64_t DefaultNowUs() {
  const auto now = std::chrono::steady_clock::now().time_since_epoch();
  return std::chrono::duration_cast<std::chrono::microseconds>(now).count();
}

void DefaultSleepUs(int64_t us) {
  if (us > 0) std::this_thread::sleep_for(std::chrono::microseconds(us));
}

}  // namespace

EgressPacer::EgressPacer()
    : now_fn_(&DefaultNowUs), sleep_fn_(&DefaultSleepUs) {}

EgressPacer::EgressPacer(NowUsFn now_fn, SleepUsFn sleep_fn)
    : now_fn_(std::move(now_fn)), sleep_fn_(std::move(sleep_fn)) {}

void EgressPacer::WaitFor(int64_t pts_us) {
  ++waits_issued_;
  const int64_t now_us = now_fn_();
  if (start_mono_us_ < 0) {
    start_mono_us_ = now_us;
    start_pts_us_ = pts_us;
    return;
  }
  const int64_t target_us = start_mono_us_ + (pts_us - start_pts_us_);
  const int64_t wait_us = target_us - now_us;
  if (wait_us > 0) {
    sleep_fn_(wait_us);
    total_sleep_us_ += wait_us;
  } else {
    ++late_releases_;
  }
}

void EgressPacer::Reset() {
  start_mono_us_ = -1;
  start_pts_us_ = -1;
}

}  // namespace retrovue::air
