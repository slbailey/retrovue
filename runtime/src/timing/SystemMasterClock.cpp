#include "retrovue/timing/MasterClock.h"

#include <atomic>
#include <chrono>
#include <cmath>
#include <iostream>
#include <memory>
#include <mutex>
#include <thread>

#ifdef _WIN32
#include <windows.h>
#endif

namespace retrovue::timing {

namespace {
constexpr double kMillion = 1'000'000.0;
}

class SystemMasterClock : public MasterClock {
 public:
  SystemMasterClock(int64_t epoch_utc_us, double rate_ppm)
      : epoch_utc_us_(epoch_utc_us),
        epoch_locked_(epoch_utc_us != 0),  // Lock if initialized with non-zero
        rate_ppm_(rate_ppm),
        drift_ppm_(0.0) {
#ifdef _WIN32
    LARGE_INTEGER freq;
    QueryPerformanceFrequency(&freq);
    qpc_frequency_inv_ = 1.0 / static_cast<double>(freq.QuadPart);
    LARGE_INTEGER counter;
    QueryPerformanceCounter(&counter);
    qpc_origin_ = counter.QuadPart;
#else
    monotonic_origin_ = std::chrono::steady_clock::now();
#endif
  }

  int64_t now_utc_us() const override {
    const auto now = std::chrono::system_clock::now();
    const auto micros =
        std::chrono::duration_cast<std::chrono::microseconds>(now.time_since_epoch());
    return micros.count();
  }

  double now_monotonic_s() const override {
#ifdef _WIN32
    LARGE_INTEGER counter;
    QueryPerformanceCounter(&counter);
    const double ticks = static_cast<double>(counter.QuadPart - qpc_origin_);
    return ticks * qpc_frequency_inv_;
#else
    const auto now = std::chrono::steady_clock::now();
    const auto delta = now - monotonic_origin_;
    return std::chrono::duration<double>(delta).count();
#endif
  }

  int64_t scheduled_to_utc_us(int64_t pts_us) const override {
    const long double scale =
        1.0L + (static_cast<long double>(rate_ppm_) + static_cast<long double>(drift_ppm_)) /
                   kMillion;
    const long double adjusted = static_cast<long double>(pts_us) * scale;
    const auto rounded = static_cast<int64_t>(std::llround(adjusted));
    return epoch_utc_us_.load(std::memory_order_acquire) + rounded;
  }

  double drift_ppm() const override { return drift_ppm_; }

  void WaitUntilUtcUs(int64_t target_utc_us) const override {
    while (true) {
      const int64_t now = now_utc_us();
      const int64_t remaining = target_utc_us - now;
      if (remaining <= 0) {
        break;
      }
      // Sleep in chunks to allow for responsive wake-up
      const int64_t sleep_us = (remaining > 2'000) ? remaining - 1'000
                                                    : std::max<int64_t>(remaining / 2, 200);
      std::this_thread::sleep_for(std::chrono::microseconds(sleep_us));
    }
  }

  void set_drift_ppm(double ppm) { drift_ppm_ = ppm; }
  void set_rate_ppm(double ppm) { rate_ppm_ = ppm; }

  // DEPRECATED: Use TrySetEpochOnce() instead.
  void set_epoch_utc_us(int64_t epoch_utc_us) override {
    if (!TrySetEpochOnce(epoch_utc_us, EpochSetterRole::LIVE)) {
      std::cerr << "[MasterClock] WARNING: set_epoch_utc_us() blocked (P7-ARCH-001)" << std::endl;
    }
  }

  // Phase 7 (P7-ARCH-001): Atomic one-time epoch set with role enforcement.
  // Uses compare_exchange_strong to prevent races between concurrent setters.
  bool TrySetEpochOnce(int64_t epoch_utc_us, EpochSetterRole role = EpochSetterRole::LIVE) override {
    // P7-ARCH-001: PREVIEW can never set epoch
    if (role == EpochSetterRole::PREVIEW) {
      std::cerr << "[MasterClock] REJECTED: Preview attempted epoch set (P7-ARCH-001)" << std::endl;
      return false;
    }

    // Atomic CAS: only one LIVE caller wins the race
    bool expected = false;
    if (!epoch_locked_.compare_exchange_strong(expected, true,
                                                std::memory_order_acq_rel,
                                                std::memory_order_acquire)) {
      // Another caller already locked - this is expected for subsequent producers
      return false;
    }

    // We won the lock - now set the epoch value
    epoch_utc_us_.store(epoch_utc_us, std::memory_order_release);
    std::cout << "[MasterClock] Epoch established by LIVE: " << epoch_utc_us << std::endl;
    return true;
  }

  // Called only on channel stop/start boundaries.
  void ResetEpochForNewSession() override {
    epoch_utc_us_.store(0, std::memory_order_release);
    epoch_locked_.store(false, std::memory_order_release);
    std::cout << "[MasterClock] Epoch reset for new session" << std::endl;
  }

  bool IsEpochLocked() const override {
    return epoch_locked_.load(std::memory_order_acquire);
  }

  int64_t get_epoch_utc_us() const override {
    return epoch_utc_us_.load(std::memory_order_acquire);
  }

 private:
  std::atomic<int64_t> epoch_utc_us_;
  std::atomic<bool> epoch_locked_;
  mutable std::mutex epoch_mutex_;  // Protects epoch set/reset operations
  double rate_ppm_;
  double drift_ppm_;
#ifdef _WIN32
  double qpc_frequency_inv_;
  int64_t qpc_origin_;
#else
  std::chrono::steady_clock::time_point monotonic_origin_;
#endif
};

std::shared_ptr<MasterClock> MakeSystemMasterClock(int64_t epoch_utc_us,
                                                   double rate_ppm) {
  return std::make_shared<SystemMasterClock>(epoch_utc_us, rate_ppm);
}

}  // namespace retrovue::timing


