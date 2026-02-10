// Repository: Retrovue-playout
// Component: Producer Bus
// Purpose: Implementation of ProducerBus.
// Copyright (c) 2025 RetroVue
//
// DEPRECATED for BlockPlan live playout.
// See ProducerBus.h and INV-PAD-PRODUCER for details.

#include "retrovue/runtime/ProducerBus.h"
#include "retrovue/producers/IProducer.h"

namespace retrovue {

void ProducerBus::reset() {
  if (producer) {
    if (producer->isRunning()) {
      producer->stop();
    }
    producer.reset();
  }
  loaded = false;
  asset_id.clear();
  file_path.clear();
}

} // namespace retrovue
