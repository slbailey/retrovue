// Repository: Retrovue-playout
// Component: DefaultProducerFactory
// Purpose: Production factory — creates real TickProducer with FFmpeg decoder.
// Copyright (c) 2026 RetroVue

#ifndef RETROVUE_BLOCKPLAN_DEFAULT_PRODUCER_FACTORY_HPP_
#define RETROVUE_BLOCKPLAN_DEFAULT_PRODUCER_FACTORY_HPP_

#include <memory>

#include "retrovue/blockplan/IProducerFactory.hpp"
#include "retrovue/blockplan/TickProducer.hpp"

namespace retrovue::blockplan {

class DefaultProducerFactory : public IProducerFactory {
 public:
  std::unique_ptr<producers::IProducer> Create(
      int width, int height, RationalFps output_fps) override {
    return std::make_unique<TickProducer>(width, height, output_fps);
  }
};

}  // namespace retrovue::blockplan

#endif  // RETROVUE_BLOCKPLAN_DEFAULT_PRODUCER_FACTORY_HPP_
