// Repository: Retrovue-playout
// Component: Deterministic Test Harness - Frame Source
// Purpose: Enum and structs for classifying frame sources in deterministic tests.
// Copyright (c) 2025 RetroVue

#ifndef RETROVUE_TESTS_HARNESS_DETERMINISTIC_FRAME_SOURCE_H_
#define RETROVUE_TESTS_HARNESS_DETERMINISTIC_FRAME_SOURCE_H_

#include <cstdint>
#include <string>

namespace retrovue::tests::harness::deterministic {

// FrameSource identifies the origin of a frame in the playout pipeline.
// Used by RecordingSink to classify frames for test assertions.
enum class FrameSource {
  LIVE_PRODUCER,  // Frame from active live producer (FileProducer, etc.)
  BLACK           // Frame from BlackFrameProducer fallback
};

// RecordedFrame captures the essential metadata for a frame consumed by the sink.
// Used to build an ordered log of frames for test assertions.
struct RecordedFrame {
  FrameSource source;         // Classification of frame origin
  std::string producer_id;    // asset_uri from frame metadata
  int64_t pts;                // Presentation timestamp
  int64_t dts;                // Decode timestamp
  int frame_index;            // Sequential index in recording

  RecordedFrame()
      : source(FrameSource::BLACK), pts(0), dts(0), frame_index(0) {}

  RecordedFrame(FrameSource src, const std::string& id, int64_t p, int64_t d, int idx)
      : source(src), producer_id(id), pts(p), dts(d), frame_index(idx) {}
};

// kBlackFrameAssetUri is the sentinel asset_uri used by BlackFrameProducer.
// RecordingSink uses this to classify frames as BLACK.
// This must match BlackFrameProducer::kAssetUri.
constexpr const char* kBlackFrameAssetUri = "internal://black";

}  // namespace retrovue::tests::harness::deterministic

#endif  // RETROVUE_TESTS_HARNESS_DETERMINISTIC_FRAME_SOURCE_H_
