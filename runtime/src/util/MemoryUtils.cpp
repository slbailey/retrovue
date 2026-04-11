// Repository: Retrovue-playout
// Component: Memory Measurement Utility
// Purpose: Lightweight RSS tracking via /proc/self/statm.
// Copyright (c) 2026 RetroVue

#include "retrovue/util/MemoryUtils.hpp"

#include <cstdio>
#include <unistd.h>

// mallinfo2 is glibc >= 2.33.  Detect at compile time.
#if defined(__GLIBC__) && (__GLIBC__ > 2 || (__GLIBC__ == 2 && __GLIBC_MINOR__ >= 33))
#include <malloc.h>
#define HAS_MALLINFO2 1
#else
#define HAS_MALLINFO2 0
#endif

namespace retrovue::util {

size_t GetRSSBytes() {
  // /proc/self/statm fields: size resident shared text lib data dt
  // We want field 2 (resident) in pages.
  FILE* f = fopen("/proc/self/statm", "r");
  if (!f) return 0;

  unsigned long size_pages = 0, resident_pages = 0;
  // Read first two fields only.
  if (fscanf(f, "%lu %lu", &size_pages, &resident_pages) != 2) {
    fclose(f);
    return 0;
  }
  fclose(f);

  static const long page_size = sysconf(_SC_PAGESIZE);
  return static_cast<size_t>(resident_pages) * static_cast<size_t>(page_size);
}

size_t GetRSSMB() {
  return GetRSSBytes() / (1024 * 1024);
}

size_t GetHeapAllocatedBytes() {
#if HAS_MALLINFO2
  struct mallinfo2 mi = mallinfo2();
  return static_cast<size_t>(mi.uordblks);
#else
  return 0;
#endif
}

}  // namespace retrovue::util
