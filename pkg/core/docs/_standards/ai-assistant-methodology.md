# AI assistant methodology

## Purpose

Establish how ChatGPT and Cursor collaborate across Retrovue repositories (core, air, docs) so every task follows the same contract-first, documentation-led workflow.

## Roles

### ChatGPT — Architect and reviewer

- Owns architecture context, requirements, and cross-repo consistency.
- Designs prompts that specify target files, required sections, style, and acceptance criteria.
- Reviews Cursor output for correctness, tone, placement, and contract alignment.
- Requests revisions until deliverables satisfy the documented standard.
- Never writes production code directly.

### Cursor — Implementer

- Executes prompts exactly as written and edits only the specified files.
- Generates documentation, code, migrations, and tests while respecting repository layout.
- Performs syntax and import checks before declaring completion.
- Runs relevant pytest or lint commands iteratively until they succeed.
- Reports completion using the `## Summary / Validation` structure (Summary, Validation/Assumptions, Follow-ups, Suggested tests).
- Avoids pasting code in chat unless explicitly instructed to do so.

## Collaboration workflow

1. **Document first** — ChatGPT instructs Cursor to draft or update documentation before any runtime code changes.
2. **Review cycle** — ChatGPT inspects the generated doc and issues revision prompts until the doc is authoritative.
3. **Implement** — ChatGPT provides a detailed code-generation prompt; Cursor writes the implementation within declared paths.
4. **Validate** — Cursor lint-checks, runs targeted tests, and self-repairs failures (Test Iteration Mode).
5. **Test authoring** — When behavior stabilizes, ChatGPT directs Cursor to add or update tests; Cursor repeats validation.
6. **Sign-off** — The duo loops until docs, code, and tests align and all validations pass.

## Prompt and output rules

- Prompts must include explicit file paths; Cursor must not infer new locations.
- Cursor must not create new top-level directories without written approval.
- Output mode defaults to in-place edits; chat replies only contain `## Summary / Validation` unless overridden.
- For long-running commands, Cursor uses background execution and reports progress in the summary.
- Any ambiguity is escalated back to ChatGPT for clarification before proceeding.

## Documentation expectations

- House tone is declarative, operational, and concise (see `documentation-standards.md`).
- Each doc begins with `## Purpose` (and `_Related:` breadcrumbs when context warrants).
- Contracts use **MUST / SHOULD / MAY** language for normative statements.
- CLI examples mirror actual command syntax and show PowerShell variants when they differ from bash.

## File placement

- Respect the canonical layout defined in `repository-conventions.md`.
- Place use cases in `src/retrovue/usecases/`, CLI wiring in `src/retrovue/cli/commands/`, and docs under `docs/`.
- Legacy code remains quarantined under `src_legacy/`; do not revive it without migration guidance.
- New standards belong in `docs/_standards/` so sibling repos can sync without duplication.

## Test iteration mode

- After modifying code or tests, Cursor runs the narrowest applicable pytest command (prefer contract suites).
- On failure, Cursor diagnoses, applies minimal fixes, and reruns until green.
- Database interactions use the configured Postgres test database; do not swap to SQLite or drop schemas.
- Cursor lists the final passing command in the summary.

## Escalation and governance

- Major process changes (e.g., new directory layers, test harnesses) require updating this document first.
- Cross-repo differences are resolved here; downstream docs add repo-specific notes only when necessary.
- ChatGPT keeps this methodology current and ensures both Retrovue Core and Retrovue Air adhere to it.

## See also

- [Documentation standards](documentation-standards.md)
- [Test methodology](test-methodology.md)
- [Repository conventions](repository-conventions.md)


