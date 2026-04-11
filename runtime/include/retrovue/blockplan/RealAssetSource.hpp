// Repository: Retrovue-playout
// Component: RealAssetSource
// Purpose: Probes real media files for duration using FFmpeg. Used by
//          TickProducer to determine asset validity and segment timing.
// Copyright (c) 2025 RetroVue

#ifndef RETROVUE_BLOCKPLAN_REAL_ASSET_SOURCE_HPP_
#define RETROVUE_BLOCKPLAN_REAL_ASSET_SOURCE_HPP_

#include <cstdint>
#include <map>
#include <string>

namespace retrovue::blockplan::realtime {

class RealAssetSource {
 public:
  // Probe asset and cache duration
  // Returns true if asset is valid
  bool ProbeAsset(const std::string& uri);

  // Get asset duration (-1 if not found/probed)
  int64_t GetDuration(const std::string& uri) const;

  // Check if asset has been probed
  bool HasAsset(const std::string& uri) const;

  struct AssetInfo {
    std::string uri;
    int64_t duration_ms = 0;
    bool valid = false;
  };

  const AssetInfo* GetAsset(const std::string& uri) const;

 private:
  std::map<std::string, AssetInfo> assets_;
};

}  // namespace retrovue::blockplan::realtime

#endif  // RETROVUE_BLOCKPLAN_REAL_ASSET_SOURCE_HPP_
