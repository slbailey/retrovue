// Repository: Retrovue-playout
// Component: Aspect Policy
// Purpose: Defines how aspect ratio is handled when scaling to ProgramFormat dimensions.
// Copyright (c) 2025 RetroVue

#ifndef RETROVUE_RUNTIME_ASPECT_POLICY_H_
#define RETROVUE_RUNTIME_ASPECT_POLICY_H_

namespace retrovue::runtime {

// AspectPolicy defines how source frames are scaled to ProgramFormat dimensions.
enum class AspectPolicy {
  Preserve,   // Scale to fit, pad with black bars (default)
  Stretch,    // Scale to fill raster, ignore aspect ratio
  Crop        // Scale to fill, crop excess (future)
};

}  // namespace retrovue::runtime

#endif  // RETROVUE_RUNTIME_ASPECT_POLICY_H_
