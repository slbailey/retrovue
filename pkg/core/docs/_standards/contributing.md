# Contributing to Retrovue documentation

## Purpose

Define the workflow for proposing, reviewing, and maintaining documentation across Retrovue repositories.

## Scope

Applies to every Markdown file under `docs/`, component READMEs, doc templates, and any architecture notes checked into the repo.

## Before you write

- For style and formatting guidance, see [`_standards/documentation-standards.md`](documentation-standards.md) and review the relevant templates in this directory.
- Search for existing coverage (`Select-String` or repo search) to avoid duplicate docs.
- Update or extend the closest existing doc before creating a new one. New doc trees require explicit approval.
- Log new glossary terms in `docs/GLOSSARY.md`.

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

- Treat files in `docs/_standards/*-template.md` as canonical. Update them only when patterns change across multiple repos.
- When editing a template, document the change in `changelog-template.md` and summarize why the pattern shifted.
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
