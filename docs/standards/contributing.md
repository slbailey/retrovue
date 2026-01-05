# Contributing to Retrovue documentation

## Purpose

Define the workflow for proposing, reviewing, and maintaining documentation across Retrovue repositories.

## Scope

Applies to every Markdown file under `docs/`, component READMEs, doc templates, and any architecture notes checked into the repo.

## Before you write

- For style and formatting guidance, see [`documentation-standards.md`](documentation-standards.md) and review the relevant templates in this directory.
- Search for existing coverage (`Select-String` or repo search) to avoid duplicate docs.
- Update or extend the closest existing doc before creating a new one. New doc trees require explicit approval.
- Log new glossary terms in `docs/GLOSSARY.md`.

## AI-Assisted Development Workflow

This project uses a combination of human expertise and AI assistance to maintain high-quality, consistent documentation and code. The following roles and workflows apply.

### Roles

*   **Architect (Human or AI-driven prompt designer):** Owns the overall architecture, requirements, and cross-repository consistency. Designs detailed prompts that specify target files, required sections, style, and acceptance criteria. Reviews AI-generated output for correctness, tone, and alignment with project standards.
*   **Implementer (AI Assistant):** Executes prompts exactly as written. Generates documentation, code, and tests, respecting existing conventions and file structures. Performs syntax checks, runs tests, and reports on the outcome.

### Collaboration Workflow

1.  **Document First:** Draft or update documentation **before** any code changes.
2.  **Review Cycle:** The Architect reviews the generated documentation and requests revisions until it is authoritative.
3.  **Implement:** The Architect provides a detailed code-generation prompt, and the Implementer writes the code.
4.  **Validate:** The Implementer runs linters and tests, self-correcting until all checks pass.
5.  **Sign-off:** The process repeats until documentation, code, and tests are all aligned and validated.

### Prompt and Output Rules

*   Prompts must include explicit file paths. The AI assistant must not infer new locations.
*   The AI assistant must not create new top-level directories without explicit approval.
*   Any ambiguity must be escalated back to the Architect for clarification before proceeding.

## Creating documentation

- Follow the template that matches your document type.
- Begin with `_Related:` breadcrumbs when there are obvious companion docs.
- Use `Purpose` as the first section. Declare scope and assumptions immediately after.
- Keep command examples executable. Prefer copy-pasteable `retrovue ...` blocks.
- Use relative links and verify they resolve locally (`Ctrl+Click` in your editor).
- For diagrams, embed Mermaid code blocks or link to the source `.mmd` file in `docs/diagrams/`.

## Updating documentation

- When behavior changes, update the contract doc **before** touching CLI code or tests.
- Sync contract docs and associated tests (`tests/contracts/...`) in the same pull request.
- When renaming sections or files, update backlinks (`_Related`, `See also`, index pages).
- Deprecate outdated guidance with a `## Status` section and note replacement docs.
- If behavior is removed, annotate the doc with `Deprecated:` and link to the removal rationale.

## Review checklist

- Purpose section matches current behavior.
- Requirements and invariants use MUST/SHOULD language.
- Examples align with the actual CLI or API outputs.
- Cross-links are accurate and reciprocal where needed.
- Style guide rules are followed (headings, tone, formatting).
- Templates remain untouched unless intentionally updated (see below).

## Template maintenance

- Treat files in `docs/standards/` (`*-template.md`) as canonical. Update them only when patterns change across multiple repos.
- When editing a template, document the change in the main `CHANGELOG.md` (or `changelog-template.md`) and summarize why the pattern shifted.
- Propagate template changes to downstream repos (retrovue-air, retrovue-docs) as part of the same initiative.

## Review process

1. Open a PR with the documentation changes.
2. Tag at least one domain owner (scheduling, ingest, runtime, etc.) if the doc touches their area.
3. Include screenshots or rendered output when diagrams or complex tables change.
4. Confirm tests affected by the documentation (e.g., contract tests) still pass.
5. Merge only after checklist items are satisfied.

## Incident documentation

- For production or contract regressions, add a `docs/dev-notes/<YYYY-MM-DD>-<slug>.md` file using the Dev Notes template.
- Capture root cause, fixes, follow-up tasks, and contract updates.
- Link the incident doc from the affected component’s README or architecture doc.

## Tooling expectations

- Markdown linting runs via CI; fix warnings locally before pushing.
- Large-scale rewrites (bulk reformatting) must be scripted and communicated in advance.
- Use Mermaid for sequence and flow diagrams (` ```mermaid ` blocks), PlantUML is not approved.

## Questions

- For repo-specific clarifications, open a discussion in GitHub or contact the maintainers listed in `docs/overview/Maintainers.md`.
- For cross-repo standard updates, coordinate in the Retrovue documentation working group channel.
