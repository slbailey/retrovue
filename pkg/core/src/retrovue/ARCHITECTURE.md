# Retrovue Code Organization (Authoritative)

We follow: **domain → contract → test → implement**.

1. All NEW business logic must be implemented as **contract-aligned usecases**.
2. Do NOT introduce new `...Service` classes under `src/retrovue/`.
3. Legacy services were moved to `src_legacy/retrovue/` and must not be re-used.
4. CLI commands must call functions from `src/retrovue/usecases/` directly.
5. Import order (prefer earlier):
   - `retrovue.domain...`
   - `retrovue.infrastructure...`
   - `retrovue.usecases...`
   - `retrovue.cli...`
6. If a test is still mocking a service class, **update the test** — do not reintroduce the service.

This file is authoritative for AI/codegen.
