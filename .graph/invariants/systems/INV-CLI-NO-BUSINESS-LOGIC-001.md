# INV-CLI-NO-BUSINESS-LOGIC-001

**Domain:** systems

## Plain-language rule

CLI commands contain **no business logic**. A CLI command may only: parse arguments, validate input shapes, manage IO (stdout, stdin prompts, progress), manage session/transaction boundaries, and call a **usecase function** or **workflow function**. Decision-making, state transitions, eligibility checks, and domain coordination belong in the usecase or workflow layer—never in the CLI handler itself.

## Why it exists

When business logic lives in CLI handlers, it becomes invisible to API consumers and untestable without simulating terminal IO. The Phase 1–2 migration (RETA-69) extracted cross-domain orchestration from `cli/commands/_ops/` into `workflows/` precisely because that logic was CLI-coupled and unreachable from the REST API. This invariant prevents regression.

## What it constrains

- **All modules under `cli/commands/`**: handlers must be thin wrappers.
- **API route handlers** (`api/routers/`): same principle—validate, call, format only.

## Failure mode if violated

- API and CLI diverge in behavior for the same operation.
- Business logic becomes untestable without CLI/HTTP simulation.
- Cross-domain coordination re-embeds in presentation layers.

## Enforcement

- Code review: any `if` branch in a CLI handler that checks domain state (not argument validation) is a violation.
- Static analysis candidate: CLI modules should not import domain model classes directly—only usecase/workflow entry points.
