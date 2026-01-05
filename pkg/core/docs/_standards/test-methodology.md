# Test methodology

## Purpose

Define the testing strategy, validation workflow, and database usage rules that govern Retrovue repositories so contract-first development stays predictable and reproducible.

## Testing hierarchy

- **Contract tests** (`tests/contracts/`) — Primary enforcement of CLI and data guarantees. Every operator-facing command has both a CLI contract test (arguments, exit codes, output) and a data contract test (state changes, database effects).
- **Unit tests** — Validate pure functions, adapters, and utility logic; focus on deterministic behavior without touching external services.
- **Integration tests** — Exercise cross-module flows (e.g., ingest pipelines) using the real database schema and configured dependencies.
- **Regression/analysis suites** — Specialized checks (e.g., `tests/CONTRACT_MIGRATION.md`) document migration paths and must remain up to date.

## Workflow expectations

1. Update the relevant contract document in `docs/contracts/` first.
2. Implement or adjust contract tests to match the documented behavior.
3. Modify application code to satisfy the updated tests.
4. Run the narrowest applicable pytest commands during iteration.
5. Before merging, run the aggregated contract suite (`pytest tests/contracts -vv`).
6. Record changes and verifications in the `## Summary / Validation` footer.

## Pytest conventions

- Use `-vv` for contract suites to keep output descriptive.
- Prefer targeted runs while iterating (e.g., `pytest tests/contracts/test_source_add_contract.py -vv`).
- Provide fixtures instead of ad-hoc setup where repeated patterns emerge.
- Keep assertions deterministic and specific; avoid broad `in (0, 1)` exit code checks unless temporarily noted with `# TODO tighten exit code once CLI stabilized`.
- Tests must not truncate or drop database schemas; rely on transaction rollbacks and fixture cleanup.

## Database rules

- Tests run against the configured Postgres URL (typically suffixed `_test`).
- Do not create alternate databases or fall back to SQLite/memory.
- Alembic migrations must be up to date before running suites (`alembic upgrade head`).
- Cleanup is logical (delete inserted rows) rather than structural (no dropping tables or schemas).
- Long-running ingest or playout scenarios should stub external services at the public seam (usecases or `_ops` helpers), never deep legacy classes.

## Validation cadence

- Cursor enters Test Iteration Mode after modifying code or tests: run pytest → inspect failures → apply minimal fixes → rerun until green.
- Summaries must list the final command executed and any assumptions (env vars, isolated DB).
- Linting (ruff, mypy) accompanies pytest for PR-ready changes; failures block merge.
- When updating templates or standards, confirm docs reference the new expectations and adjust tests if behavior shifts.

## Data integrity and safety

- Contract tests enforce exit codes, human-readable output, JSON payload structure, and database effects.
- Destructive commands require explicit confirmation flags and must be covered by both CLI and data contracts.
- Ingest tests operate in discovery-only mode; do not resurrect deprecated orchestrators.
- Asset updates must respect canonical rules (downgrade state, reset approvals, record stats) and track metrics in JSON stats.

## When to add tests

- New CLI verbs, flags, or output changes.
- New domain invariants or schema fields.
- Bug fixes that rely on behavior previously untested.
- Refactors that alter control flow, timing, or data access patterns.

## See also

- [AI assistant methodology](ai-assistant-methodology.md)
- [Documentation standards](documentation-standards.md)
- [Repository conventions](repository-conventions.md)


