// Repository: Retrovue-playout
// Component: IProducerFactory
// Purpose: Injection point for TickProducer creation.  Production code uses
//          DefaultProducerFactory (creates real TickProducer with FFmpeg decoder).
//          Test harnesses substitute TestProducerFactory to generate deterministic
//          frames without I/O dependencies.
// Copyright (c) 2026 RetroVue

#ifndef RETROVUE_BLOCKPLAN_IPRODUCER_FACTORY_HPP_
#define RETROVUE_BLOCKPLAN_IPRODUCER_FACTORY_HPP_

#include <memory>

#include "retrovue/blockplan/RationalFps.hpp"
#include "retrovue/producers/IProducer.h"

namespace retrovue::blockplan {

class IProducerFactory {
 public:
  virtual ~IProducerFactory() = default;

  // Create a new IProducer that also implements ITickProducer.
  // Production: returns TickProducer (FFmpeg decoder).
  // Tests: returns TestDecoder (deterministic frames, no I/O).
  virtual std::unique_ptr<producers::IProducer> Create(
      int width, int height, RationalFps output_fps) = 0;
};

}  // namespace retrovue::blockplan

#endif  // RETROVUE_BLOCKPLAN_IPRODUCER_FACTORY_HPP_
