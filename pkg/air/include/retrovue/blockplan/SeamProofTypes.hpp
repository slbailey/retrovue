// Repository: Retrovue-playout
// Component: Seam Proof Types
// Purpose: Header-only types and utilities for P3.2 seam verification.
//          CRC32 fingerprinting of Y plane, boundary report generation.
// Contract Reference: PlayoutAuthorityContract.md (P3.2)
// Copyright (c) 2025 RetroVue

#ifndef RETROVUE_BLOCKPLAN_SEAM_PROOF_TYPES_HPP_
#define RETROVUE_BLOCKPLAN_SEAM_PROOF_TYPES_HPP_

#include <algorithm>
#include <cstdint>
#include <iostream>
#include <string>
#include <vector>

#include <zlib.h>

namespace retrovue::blockplan {

// Number of Y-plane bytes to fingerprint (first 4096).
static constexpr size_t kFingerprintYBytes = 4096;

// CRC32 of the first min(y_size, kFingerprintYBytes) bytes of Y plane data.
// Returns 0 if y_data is null or y_size is 0.
inline uint32_t CRC32YPlane(const uint8_t* y_data, size_t y_size) {
  if (!y_data || y_size == 0) return 0;
  size_t len = std::min(y_size, kFingerprintYBytes);
  return static_cast<uint32_t>(
      crc32(crc32(0L, Z_NULL, 0), y_data, static_cast<uInt>(len)));
}

// Per-frame fingerprint record emitted via on_frame_emitted callback.
struct FrameFingerprint {
  int64_t session_frame_index = 0;
  bool is_pad = true;
  std::string active_block_id;
  std::string asset_uri;
  int64_t asset_offset_ms = 0;  // block_ct_ms before frame advance
  uint32_t y_crc32 = 0;
  // TAKE source: 'A' = popped from current (live) buffer,
  //              'B' = popped from preview (preroll) buffer,
  //              'P' = pad frame (no buffer supplied this tick).
  // Set at the commitment point — authoritative for TAKE verification.
  char commit_source = 'P';
};

// Boundary report: last kWindow frames of block A + first kWindow of block B.
struct BoundaryReport {
  static constexpr int kWindow = 5;

  std::string block_a_id;
  std::string block_b_id;
  std::vector<FrameFingerprint> tail_a;
  std::vector<FrameFingerprint> head_b;
  int64_t fence_frame_index = 0;
  int pad_frames_in_window = 0;  // pad frames in [fence-kWindow+1, fence+kWindow-1]
};

// Build a BoundaryReport from a full fingerprint vector.
// fence_index: the session_frame_index of the first frame of block B.
inline BoundaryReport BuildBoundaryReport(
    const std::vector<FrameFingerprint>& all_fps,
    int64_t fence_index,
    const std::string& block_a_id,
    const std::string& block_b_id) {
  BoundaryReport report;
  report.block_a_id = block_a_id;
  report.block_b_id = block_b_id;
  report.fence_frame_index = fence_index;
  report.pad_frames_in_window = 0;

  // Collect tail of block A: frames [fence - kWindow, fence - 1]
  for (int64_t i = fence_index - BoundaryReport::kWindow;
       i < fence_index; i++) {
    if (i >= 0 && i < static_cast<int64_t>(all_fps.size())) {
      report.tail_a.push_back(all_fps[static_cast<size_t>(i)]);
      if (all_fps[static_cast<size_t>(i)].is_pad) {
        report.pad_frames_in_window++;
      }
    }
  }

  // Collect head of block B: frames [fence, fence + kWindow - 1]
  for (int64_t i = fence_index;
       i < fence_index + BoundaryReport::kWindow; i++) {
    if (i >= 0 && i < static_cast<int64_t>(all_fps.size())) {
      report.head_b.push_back(all_fps[static_cast<size_t>(i)]);
      if (all_fps[static_cast<size_t>(i)].is_pad) {
        report.pad_frames_in_window++;
      }
    }
  }

  return report;
}

// Print a boundary report for diagnostic output.
inline void PrintBoundaryReport(std::ostream& os,
                                 const BoundaryReport& report) {
  os << "=== Boundary Report ===\n";
  os << "Block A: " << report.block_a_id << "\n";
  os << "Block B: " << report.block_b_id << "\n";
  os << "Fence frame index: " << report.fence_frame_index << "\n";
  os << "Pad frames in window: " << report.pad_frames_in_window << "\n";

  auto print_fp = [&os](const FrameFingerprint& fp) {
    os << "  [" << fp.session_frame_index << "] "
       << (fp.is_pad ? "PAD" : "REAL")
       << " block=" << fp.active_block_id
       << " uri=" << fp.asset_uri
       << " offset_ms=" << fp.asset_offset_ms
       << " y_crc32=0x" << std::hex << fp.y_crc32 << std::dec
       << "\n";
  };

  os << "Tail A (" << report.tail_a.size() << " frames):\n";
  for (const auto& fp : report.tail_a) print_fp(fp);

  os << "Head B (" << report.head_b.size() << " frames):\n";
  for (const auto& fp : report.head_b) print_fp(fp);

  os << "=======================\n";
}

}  // namespace retrovue::blockplan

#endif  // RETROVUE_BLOCKPLAN_SEAM_PROOF_TYPES_HPP_
