// Repository: Retrovue-playout
// Component: ProgramFormat Domain
// Purpose: Canonical per-channel program signal format definition.
// Copyright (c) 2025 RetroVue

#ifndef RETROVUE_RUNTIME_PROGRAM_FORMAT_H_
#define RETROVUE_RUNTIME_PROGRAM_FORMAT_H_

#include <cstdint>
#include <optional>
#include <string>

namespace retrovue::runtime {

// ProgramFormat defines the canonical program signal produced by a channel.
// It is per-channel, fixed for the lifetime of a PlayoutInstance, and
// independent of encoding, muxing, or transport.
//
// See: docs/air/contracts/PlayoutInstanceAndProgramFormatContract.md
struct ProgramFormat {
  // Video format
  struct Video {
    int32_t width;           // Video width in pixels
    int32_t height;          // Video height in pixels
    std::string frame_rate;  // Rational string (e.g., "30000/1001", "25/1")
    std::string aspect_policy;  // "preserve" (default), "stretch", "crop"

    Video() : width(0), height(0), frame_rate("30/1"), aspect_policy("preserve") {}
    Video(int32_t w, int32_t h, const std::string& fr)
        : width(w), height(h), frame_rate(fr), aspect_policy("preserve") {}
  } video;
  
  // Audio format
  struct Audio {
    int32_t sample_rate;     // Sample rate in Hz
    int32_t channels;        // Channel count
    
    Audio() : sample_rate(48000), channels(2) {}
    Audio(int32_t sr, int32_t ch) : sample_rate(sr), channels(ch) {}
  } audio;
  
  ProgramFormat() = default;
  ProgramFormat(const Video& v, const Audio& a) : video(v), audio(a) {}
  
  // Parse ProgramFormat from JSON string.
  // Returns empty optional on parse/validation failure.
  static std::optional<ProgramFormat> FromJson(const std::string& json_str);
  
  // Convert to JSON string (for debugging/logging).
  std::string ToJson() const;
  
  // Validate that all required fields are present and valid.
  bool IsValid() const;
  
  // Convert frame_rate rational string to double (e.g., "30000/1001" -> 29.97).
  // Returns 0.0 on parse failure.
  double GetFrameRateAsDouble() const;
};

}  // namespace retrovue::runtime

#endif  // RETROVUE_RUNTIME_PROGRAM_FORMAT_H_
