# INV-PRODUCTION-BOUNDARY-001

**Domain:** systems

## Plain-language rule

**Production code paths** must not contain mocks, fakes, test harnesses, or test-only types; protocols live in the designated protocol surface; test doubles live under tests/fixtures.

## Why it exists

Keeps audits honest: what ships is what you read. Prevents test types from **accidentally** running in production via bad flags.

## What it constrains

- Layout and classification of **modules** (runtime vs tests), not domain semantics.

## Failure mode if violated

False confidence in production behavior, enlarged attack/misconfig surface, and reviews that cannot tell **real** from **stub** code.
