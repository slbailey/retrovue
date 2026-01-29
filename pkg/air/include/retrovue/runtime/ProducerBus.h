// Repository: Retrovue-playout
// Component: Producer Bus
// Purpose: Abstraction for managing a producer on a bus (preview or live).
// Copyright (c) 2025 RetroVue

#ifndef RETROVUE_RUNTIME_PRODUCER_BUS_H_
#define RETROVUE_RUNTIME_PRODUCER_BUS_H_

#include <memory>
#include <string>

namespace retrovue::producers {
  class IProducer;
}

namespace retrovue {

// ProducerBus represents a routed producer input path
// (e.g. LIVE or PREVIEW) in a playout engine.
//
// A bus is not storage.
// A bus may be empty, primed, or active.
// Buses can be switched atomically by the PlayoutControl.
struct ProducerBus {
  std::unique_ptr<producers::IProducer> producer;
  bool loaded = false;
  std::string asset_id;
  std::string file_path;

  // Resets the bus to empty state.
  void reset();
};

} // namespace retrovue

#endif // RETROVUE_RUNTIME_PRODUCER_BUS_H_
