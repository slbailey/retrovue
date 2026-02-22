// Repository: Retrovue-playout
// Component: RealAssetSource Implementation
// Purpose: Probes real media files for duration using FFmpeg
// Copyright (c) 2025 RetroVue

#include "retrovue/blockplan/RealAssetSource.hpp"

#include <chrono>
#include <iostream>

#ifdef RETROVUE_FFMPEG_AVAILABLE
extern "C" {
#include <libavformat/avformat.h>
}
#endif

namespace retrovue::blockplan::realtime {

bool RealAssetSource::ProbeAsset(const std::string& uri) {
#ifdef RETROVUE_FFMPEG_AVAILABLE
  AVFormatContext* fmt_ctx = nullptr;

  auto open_start = std::chrono::steady_clock::now();
  if (avformat_open_input(&fmt_ctx, uri.c_str(), nullptr, nullptr) < 0) {
    std::cerr << "[RealAssetSource] Failed to open: " << uri << std::endl;
    return false;
  }
  auto open_end = std::chrono::steady_clock::now();
  auto open_ms = std::chrono::duration_cast<std::chrono::milliseconds>(
      open_end - open_start).count();
#ifdef RETROVUE_DEBUG
  std::cout << "[METRIC] asset_open_input_ms=" << open_ms
            << " uri=" << uri << std::endl;
#endif

  auto stream_info_start = std::chrono::steady_clock::now();
  if (avformat_find_stream_info(fmt_ctx, nullptr) < 0) {
    avformat_close_input(&fmt_ctx);
    std::cerr << "[RealAssetSource] Failed to find stream info: " << uri << std::endl;
    return false;
  }
  auto stream_info_end = std::chrono::steady_clock::now();
  auto stream_info_ms = std::chrono::duration_cast<std::chrono::milliseconds>(
      stream_info_end - stream_info_start).count();
#ifdef RETROVUE_DEBUG
  std::cout << "[METRIC] asset_stream_info_ms=" << stream_info_ms
            << " uri=" << uri << std::endl;
#endif

  // Get duration in milliseconds
  int64_t duration_ms = 0;
  if (fmt_ctx->duration != AV_NOPTS_VALUE) {
    duration_ms = fmt_ctx->duration / 1000;  // AV_TIME_BASE is microseconds
  }

  avformat_close_input(&fmt_ctx);

  AssetInfo info;
  info.uri = uri;
  info.duration_ms = duration_ms;
  info.valid = true;
  assets_[uri] = info;

  std::cout << "[RealAssetSource] Probed: " << uri << " (" << duration_ms << "ms)" << std::endl;
  return true;
#else
  (void)uri;
  std::cerr << "[RealAssetSource] FFmpeg not available" << std::endl;
  return false;
#endif
}

int64_t RealAssetSource::GetDuration(const std::string& uri) const {
  auto it = assets_.find(uri);
  if (it == assets_.end()) return -1;
  return it->second.duration_ms;
}

bool RealAssetSource::HasAsset(const std::string& uri) const {
  return assets_.find(uri) != assets_.end();
}

const RealAssetSource::AssetInfo* RealAssetSource::GetAsset(const std::string& uri) const {
  auto it = assets_.find(uri);
  if (it == assets_.end()) return nullptr;
  return &it->second;
}

}  // namespace retrovue::blockplan::realtime
