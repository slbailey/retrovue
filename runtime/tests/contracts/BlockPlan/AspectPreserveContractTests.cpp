// Repository: Retrovue-playout
// Component: Aspect Ratio Preservation Contract Tests
// Purpose: INV-ASPECT-PRESERVE-001 — validate SAR-aware scaling math
//          in FFmpegDecoder and aspect_policy flow through ProgramFormat.
// Copyright (c) 2025 RetroVue

#include <gtest/gtest.h>

#include "retrovue/runtime/AspectPolicy.h"
#include "retrovue/runtime/ProgramFormat.h"
#include "retrovue/decode/FFmpegDecoder.h"

using namespace retrovue;

// =============================================================================
// INV-ASPECT-PRESERVE-001: ProgramFormat round-trip with aspect_policy
// =============================================================================

TEST(AspectPreserveContract, ProgramFormatDefaultAspectPolicy) {
  runtime::ProgramFormat pf;
  pf.video.width = 1280;
  pf.video.height = 720;
  pf.video.frame_rate = "30000/1001";
  pf.audio.sample_rate = 48000;
  pf.audio.channels = 2;

  // Default aspect_policy MUST be "preserve"
  EXPECT_EQ(pf.video.aspect_policy, "preserve");
}

TEST(AspectPreserveContract, ProgramFormatJsonIncludesAspectPolicy) {
  runtime::ProgramFormat pf;
  pf.video.width = 1280;
  pf.video.height = 720;
  pf.video.frame_rate = "30000/1001";
  pf.audio.sample_rate = 48000;
  pf.audio.channels = 2;

  std::string json = pf.ToJson();

  // JSON MUST contain aspect_policy
  EXPECT_NE(json.find("\"aspect_policy\""), std::string::npos)
      << "ToJson() must include aspect_policy field. Got: " << json;
  EXPECT_NE(json.find("\"preserve\""), std::string::npos)
      << "Default aspect_policy must be 'preserve'. Got: " << json;
}

TEST(AspectPreserveContract, ProgramFormatFromJsonReadsAspectPolicy) {
  std::string json = R"({
    "video": {"width": 1280, "height": 720, "frame_rate": "30000/1001", "aspect_policy": "stretch"},
    "audio": {"sample_rate": 48000, "channels": 2}
  })";

  auto result = runtime::ProgramFormat::FromJson(json);
  ASSERT_TRUE(result.has_value());
  EXPECT_EQ(result->video.aspect_policy, "stretch");
}

TEST(AspectPreserveContract, ProgramFormatFromJsonDefaultsToPreserve) {
  // JSON without aspect_policy MUST default to "preserve"
  std::string json = R"({
    "video": {"width": 1280, "height": 720, "frame_rate": "30000/1001"},
    "audio": {"sample_rate": 48000, "channels": 2}
  })";

  auto result = runtime::ProgramFormat::FromJson(json);
  ASSERT_TRUE(result.has_value());
  EXPECT_EQ(result->video.aspect_policy, "preserve");
}

// =============================================================================
// INV-ASPECT-PRESERVE-001: DecoderConfig carries aspect_policy
// =============================================================================

TEST(AspectPreserveContract, DecoderConfigDefaultAspectPolicy) {
  decode::DecoderConfig config;
  EXPECT_EQ(config.aspect_policy, runtime::AspectPolicy::Preserve);
}

// =============================================================================
// INV-ASPECT-PRESERVE-001: FFmpegDecoder exposes scaling geometry
//
// These tests validate that the scaling math fields exist and are accessible.
// Full integration tests with real media files validate the actual computation.
// =============================================================================

TEST(AspectPreserveContract, FFmpegDecoderHasScalingGeometry) {
  decode::DecoderConfig config;
  config.target_width = 1280;
  config.target_height = 720;
  config.aspect_policy = runtime::AspectPolicy::Preserve;

  decode::FFmpegDecoder decoder(config);

  // Before Open(), scaling geometry should be zero/default
  EXPECT_EQ(decoder.GetScaleWidth(), 0);
  EXPECT_EQ(decoder.GetScaleHeight(), 0);
  EXPECT_EQ(decoder.GetPadX(), 0);
  EXPECT_EQ(decoder.GetPadY(), 0);
}
