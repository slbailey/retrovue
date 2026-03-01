// Repository: Retrovue-playout
// Component: ProgramFormat Domain Implementation
// Purpose: Parse and validate ProgramFormat from JSON.
// Copyright (c) 2025 RetroVue

#include "retrovue/runtime/ProgramFormat.h"

#include <sstream>
#include <stdexcept>
#include <optional>
#include <regex>

namespace retrovue::runtime {

namespace {
  // Simple JSON parser for ProgramFormat schema.
  // Since the schema is fixed and simple, we parse manually rather than adding a dependency.
  
  // Extract integer value from JSON object field
  bool ExtractInt(const std::string& json, const std::string& field_name, int32_t& out_value) {
    std::string pattern_str = "\"" + field_name + "\"\\s*:\\s*(\\d+)";
    std::regex pattern(pattern_str);
    std::smatch match;
    if (std::regex_search(json, match, pattern)) {
      try {
        out_value = std::stoi(match[1].str());
        return true;
      } catch (...) {
        return false;
      }
    }
    return false;
  }
  
  // Extract string value from JSON object field
  bool ExtractString(const std::string& json, const std::string& field_name, std::string& out_value) {
    std::string pattern_str = "\"" + field_name + "\"\\s*:\\s*\"([^\"]+)\"";
    std::regex pattern(pattern_str);
    std::smatch match;
    if (std::regex_search(json, match, pattern)) {
      out_value = match[1].str();
      return true;
    }
    return false;
  }
  
  // Extract nested object (e.g., "video": { ... })
  bool ExtractNestedObject(const std::string& json, const std::string& field_name, std::string& out_json) {
    std::string pattern_str = "\"" + field_name + "\"\\s*:\\s*\\{";
    std::regex pattern(pattern_str);
    std::smatch match;
    if (!std::regex_search(json, match, pattern)) {
      return false;
    }
    
    // Find the opening brace after the field name
    size_t start_pos = match.position() + match.length() - 1; // Position of '{'
    int brace_count = 1;
    size_t pos = start_pos + 1;
    
    while (pos < json.length() && brace_count > 0) {
      if (json[pos] == '{') brace_count++;
      else if (json[pos] == '}') brace_count--;
      pos++;
    }
    
    if (brace_count == 0) {
      out_json = json.substr(start_pos, pos - start_pos);
      return true;
    }
    return false;
  }
  
  // Validate frame_rate is a rational string (e.g., "30000/1001", "25/1")
  bool IsValidFrameRate(const std::string& frame_rate) {
    std::regex pattern(R"(\d+/\d+)");
    return std::regex_match(frame_rate, pattern);
  }
}

std::optional<ProgramFormat> ProgramFormat::FromJson(const std::string& json_str) {
  if (json_str.empty()) {
    return std::nullopt;
  }
  
  ProgramFormat format;
  
  // Extract video object
  std::string video_json;
  if (!ExtractNestedObject(json_str, "video", video_json)) {
    return std::nullopt;
  }
  
  // Extract video fields
  if (!ExtractInt(video_json, "width", format.video.width)) {
    return std::nullopt;
  }
  if (!ExtractInt(video_json, "height", format.video.height)) {
    return std::nullopt;
  }
  if (!ExtractString(video_json, "frame_rate", format.video.frame_rate)) {
    return std::nullopt;
  }
  if (!IsValidFrameRate(format.video.frame_rate)) {
    return std::nullopt;
  }

  // Extract aspect_policy (optional, defaults to "preserve")
  std::string aspect_policy;
  if (ExtractString(video_json, "aspect_policy", aspect_policy)) {
    format.video.aspect_policy = aspect_policy;
  }
  // else: default "preserve" from Video() constructor

  // Extract audio object
  std::string audio_json;
  if (!ExtractNestedObject(json_str, "audio", audio_json)) {
    return std::nullopt;
  }
  
  // Extract audio fields
  if (!ExtractInt(audio_json, "sample_rate", format.audio.sample_rate)) {
    return std::nullopt;
  }
  if (!ExtractInt(audio_json, "channels", format.audio.channels)) {
    return std::nullopt;
  }
  
  // Validate all fields
  if (!format.IsValid()) {
    return std::nullopt;
  }
  
  return format;
}

std::string ProgramFormat::ToJson() const {
  std::ostringstream oss;
  oss << "{"
      << "\"video\":{"
      << "\"width\":" << video.width << ","
      << "\"height\":" << video.height << ","
      << "\"frame_rate\":\"" << video.frame_rate << "\","
      << "\"aspect_policy\":\"" << video.aspect_policy << "\""
      << "},"
      << "\"audio\":{"
      << "\"sample_rate\":" << audio.sample_rate << ","
      << "\"channels\":" << audio.channels
      << "}"
      << "}";
  return oss.str();
}

bool ProgramFormat::IsValid() const {
  // Validate video
  if (video.width <= 0 || video.height <= 0) {
    return false;
  }
  if (!IsValidFrameRate(video.frame_rate)) {
    return false;
  }
  
  // Validate audio
  if (audio.sample_rate <= 0) {
    return false;
  }
  if (audio.channels <= 0) {
    return false;
  }
  
  return true;
}

double ProgramFormat::GetFrameRateAsDouble() const {
  // Parse rational string (e.g., "30000/1001" -> 29.97)
  std::regex pattern(R"((\d+)/(\d+))");
  std::smatch match;
  if (std::regex_match(video.frame_rate, match, pattern)) {
    try {
      double numerator = std::stod(match[1].str());
      double denominator = std::stod(match[2].str());
      if (denominator != 0.0) {
        return numerator / denominator;
      }
    } catch (...) {
      // Fall through to return 0.0
    }
  }
  return 0.0;
}

}  // namespace retrovue::runtime
