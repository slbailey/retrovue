#!/usr/bin/env python3
"""
RETA-67: jemalloc vs glibc malloc RSS benchmark for RetroVue.

Simulates RetroVue's dominant allocation pattern: high-churn bytes objects
cycling through bounded deques (TsRingBuffer / SegmentRing pattern).

Usage:
  # glibc (baseline):
  python3 tools/bench_jemalloc_rss.py

  # jemalloc:
  LD_PRELOAD=/usr/lib/x86_64-linux-gnu/libjemalloc.so.2 python3 tools/bench_jemalloc_rss.py

Outputs CSV-style RSS measurements after each block-fill cycle.
"""
from __future__ import annotations

import ctypes
import ctypes.util
import os
import sys
import time
from collections import deque

# ── Configuration ──────────────────────────────────────────────────
RING_MAX_BYTES = 8 * 1024 * 1024       # 8 MiB per ring (matches TsRingBuffer default)
CHUNK_SIZE = 188 * 7                    # 1316 bytes — 7 TS packets, typical read chunk
NUM_RINGS = 4                           # Simulate 4 active channels
FILL_CYCLES = 20                        # Number of complete fill-and-drain cycles
DRAIN_FRACTION = 0.8                    # Drain 80% of each ring per cycle


def get_rss_mb() -> float:
    """Current RSS from /proc/self/statm (Linux only)."""
    with open("/proc/self/statm") as f:
        resident_pages = int(f.read().split()[1])
    return resident_pages * os.sysconf("SC_PAGE_SIZE") / 1048576


def detect_allocator() -> str:
    """Best-effort detection of active malloc implementation."""
    ld_preload = os.environ.get("LD_PRELOAD", "")
    if "jemalloc" in ld_preload:
        return "jemalloc (LD_PRELOAD)"
    # Check if jemalloc symbols are present
    try:
        libc = ctypes.CDLL(None)
        if hasattr(libc, "mallctl"):
            return "jemalloc (linked)"
    except Exception:
        pass
    return "glibc"


def simulate_ring_churn(
    rings: list[deque[bytes]],
    max_bytes: int,
    chunk_size: int,
    drain_fraction: float,
) -> None:
    """One fill-then-drain cycle across all rings."""
    # Fill phase: push chunks until each ring is full
    chunks_per_ring = max_bytes // chunk_size
    for ring in rings:
        for _ in range(chunks_per_ring):
            ring.append(os.urandom(chunk_size))
            # Evict oldest when over budget (same as TsRingBuffer.put)
            total = sum(len(c) for c in ring)
            while total > max_bytes and len(ring) > 1:
                old = ring.popleft()
                total -= len(old)

    # Drain phase: remove drain_fraction of each ring
    for ring in rings:
        drain_count = int(len(ring) * drain_fraction)
        for _ in range(drain_count):
            if ring:
                ring.popleft()


def main() -> None:
    allocator = detect_allocator()
    print(f"# RETA-67 jemalloc benchmark")
    print(f"# Allocator: {allocator}")
    print(f"# Rings: {NUM_RINGS}, Ring max: {RING_MAX_BYTES // 1024}KB, "
          f"Chunk: {CHUNK_SIZE}B, Cycles: {FILL_CYCLES}")
    print(f"# Drain fraction: {DRAIN_FRACTION}")
    print()
    print("cycle,rss_mb,delta_from_baseline_mb,elapsed_s")

    rings: list[deque[bytes]] = [deque() for _ in range(NUM_RINGS)]
    baseline_rss = get_rss_mb()
    t0 = time.monotonic()

    for cycle in range(1, FILL_CYCLES + 1):
        simulate_ring_churn(rings, RING_MAX_BYTES, CHUNK_SIZE, DRAIN_FRACTION)
        rss = get_rss_mb()
        elapsed = time.monotonic() - t0
        print(f"{cycle},{rss:.1f},{rss - baseline_rss:.1f},{elapsed:.1f}")
        sys.stdout.flush()

    # Final measurement after clearing all rings
    for ring in rings:
        ring.clear()
    # Give allocator a chance to return pages
    import gc
    gc.collect()
    time.sleep(0.5)
    final_rss = get_rss_mb()
    print()
    print(f"# After clear + gc.collect: RSS={final_rss:.1f} MB "
          f"(delta={final_rss - baseline_rss:.1f} MB from baseline)")
    print(f"# Baseline RSS was {baseline_rss:.1f} MB")


if __name__ == "__main__":
    main()
