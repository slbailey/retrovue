# <Project name> — Documentation Index

_Metadata: Status=Canonical • Scope=Documentation index_

## Purpose

Explain how the documentation set is organized, who each section serves, and point readers to the most relevant entry points.

## How this template works

- Organize sections by audience or intent (Architecture, Domain Models, Contracts, Runtime, Developer, Infrastructure, Testing, Milestones).
- Keep descriptions short and operational (one line per entry).
- Use relative links and sentence-case headings.
- Add `## Status` at the end if the documentation index is experimental or deprecated.

## Example structure

```markdown
## Architecture

- [Architecture Overview](architecture/ArchitectureOverview.md) — System context
- [Project Overview](PROJECT_OVERVIEW.md) — Program-level goals

## Domain Models

- [Renderer Domain](domain/RendererDomain.md) — Rendering subsystem behavior
- [Metrics Domain](domain/MetricsDomain.md) — Telemetry entities and invariants

## Contracts

- [Renderer Contract](contracts/RendererContract.md) — Output guarantees
- [Metrics Contract](contracts/MetricsContract.md) — Metric naming and alerting

## Developer Guides

- [Quick Start](developer/QuickStart.md) — Build and run flow
- [Build & Debug](developer/BuildAndDebug.md) — Toolchain specifics
```

## Tips

- Include a short “Documentation Principles” section if the repo has unique navigation rules.
- Provide “Quick links” for the most common workflows (understand architecture, run tests, file issues).
- Close with `## Status` only when the index is deprecated or under active rewrite.

