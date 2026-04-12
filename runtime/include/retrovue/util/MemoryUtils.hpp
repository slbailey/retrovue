// Repository: Retrovue-playout
// Component: Memory Measurement Utility
// Purpose: Lightweight RSS tracking for long-running soak diagnostics.
//          Reads /proc/self/statm — no allocations, no external deps.
// Copyright (c) 2026 RetroVue

#ifndef RETROVUE_UTIL_MEMORY_UTILS_HPP_
#define RETROVUE_UTIL_MEMORY_UTILS_HPP_

#include <cstddef>
#include <cstdint>

namespace retrovue::util {

// Read current RSS from /proc/self/statm.  Returns 0 on failure.
size_t GetRSSBytes();

// Convenience: RSS in whole megabytes (truncated).
size_t GetRSSMB();

// If mallinfo2() is available, return total allocated arena bytes (uordblks).
// Returns 0 if unavailable or on error.
size_t GetHeapAllocatedBytes();

}  // namespace retrovue::util

#endif  // RETROVUE_UTIL_MEMORY_UTILS_HPP_
