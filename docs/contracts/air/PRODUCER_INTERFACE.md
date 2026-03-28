# Producer Interface — AIR Behavioral Contract

Status: Contract
Authority Level: Runtime
Derived From: `LAW-LIVENESS`, `LAW-SWITCHING`
Owner: AIR (PipelineManager / ITickProducer / IProducerFactory)

---

## Purpose

This contract governs how PipelineManager interacts with producers created by `IProducerFactory`. The factory returns `IProducer` objects that implement `ITickProducer`. PipelineManager MUST access these producers exclusively through the `ITickProducer` interface. Concrete-type downcasts to `TickProducer` are forbidden on factory-produced paths because the factory contract permits non-`TickProducer` implementations (e.g., `TestDecoder`).

---

## Invariants

### INV-AIR-PRODUCER-INTERFACE-001

#### Behavioral Guarantee

PipelineManager accesses all factory-produced producers exclusively through `ITickProducer`-compatible interface methods. No heap-buffer-overflow, use-after-free, or undefined behavior can occur from type mismatch between the factory return type and the interface used by the caller.

#### Authority Model

`IProducerFactory::Create()` returns `unique_ptr<IProducer>`. `PipelineManager::AsTickProducer()` performs `dynamic_cast<ITickProducer*>` to obtain the tick interface. All tick-method calls go through this interface pointer.

#### Boundary / Constraint

- PipelineManager MUST NOT use `static_cast<TickProducer*>` on any pointer obtained from `CreateProducer()` or `IProducerFactory::Create()`.
- PipelineManager MUST use `AsTickProducer()` (which performs `dynamic_cast<ITickProducer*>`) for all tick-method access.
- Any behavior required by PipelineManager from a producer MUST be available on `ITickProducer` (as a pure virtual or defaulted virtual method).

#### Violation

A `static_cast<TickProducer*>` on a factory-produced `IProducer` pointer. Accessing a `TickProducer`-specific member (not on `ITickProducer`) through a factory-produced pointer. Heap-buffer-overflow from reading past the allocation of a non-`TickProducer` implementation.

#### Required Tests

- `pkg/air/tests/contracts/BlockPlan/ContinuousOutputContractTests.cpp` — `BlockCompletedCallbackFires` + `StopDuringBlockExecution` sequence (regression: segfault from unsafe cast)

#### Enforcement Evidence

TODO

---

### INV-AIR-PRODUCER-PRIME-001

#### Behavioral Guarantee

Audio priming (`PrimeFirstTick`) is available to PipelineManager for any producer implementation without requiring knowledge of the concrete type. Producers that do not support real decoding return a safe default.

#### Authority Model

`ITickProducer::PrimeFirstTick()` is a virtual method with a default implementation returning `{false, 0}`. `TickProducer` overrides with real decode-based priming. `TestDecoder` and other stubs override with priming from their synthetic frame generation.

#### Boundary / Constraint

- `PrimeFirstTick()` MUST be declared on `ITickProducer` with a safe default (`{false, 0}`).
- PipelineManager MUST call `PrimeFirstTick()` through the `ITickProducer` interface, not through a concrete `TickProducer` downcast.
- Producers that do not support priming MUST NOT crash, abort, or produce undefined behavior when `PrimeFirstTick()` is called.
- The `PrimeResult` struct MUST be defined on `ITickProducer`, not on `TickProducer`.

#### Violation

A `PrimeFirstTick()` call that requires the caller to know the concrete producer type. A `PrimeResult` type that is only accessible through `TickProducer.hpp`.

#### Required Tests

- `pkg/air/tests/contracts/BlockPlan/ContinuousOutputContractTests.cpp` — `BlockCompletedCallbackFires` (uses TestProducerFactory; PrimeFirstTick must not crash)

#### Enforcement Evidence

TODO

---

### INV-AIR-PRODUCER-ASPECT-001

#### Behavioral Guarantee

Aspect policy configuration is available to PipelineManager and SeamPreparer for any producer implementation without requiring concrete-type downcasts.

#### Authority Model

`ITickProducer::SetAspectPolicy()` is a virtual method with a default no-op implementation. `TickProducer` overrides to configure the FFmpeg decoder scaling pipeline.

#### Boundary / Constraint

- `SetAspectPolicy()` MUST be declared on `ITickProducer` with a no-op default.
- PipelineManager MUST call `SetAspectPolicy()` through the `ITickProducer` interface or `AsTickProducer()`.
- `static_cast<TickProducer*>` for aspect policy application is forbidden.

#### Violation

A `static_cast<TickProducer*>` used to call `SetAspectPolicy()` on a factory-produced producer. A crash when `SetAspectPolicy()` is called on a non-`TickProducer` implementation.

#### Required Tests

- `pkg/air/tests/contracts/BlockPlan/ContinuousOutputContractTests.cpp` — any test using `TestProducerFactory` exercises this path

#### Enforcement Evidence

TODO
