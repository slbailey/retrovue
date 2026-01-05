# <Component or package name>

_Related: [Link to sibling doc](../path/to/doc.md) • [Link to glossary entry](../GLOSSARY.md)_

## Purpose

Explain what this component does and why it exists. Keep it to 2–3 concise sentences.

## Scope

- Bullet the responsibilities this component owns.
- Call out what is explicitly out of scope (prefer “Out of scope” sub-heading if longer).

## Status

- **Lifecycle:** experimental | beta | stable | deprecated
- **Owner:** @team-handle or individual maintainer
- **Last review:** YYYY-MM-DD

## Audience

Describe who should read this README (operators, plugin authors, runtime engineers).

## Contract summary

- Link to primary contract docs (e.g., `docs/contracts/resources/ChannelContract.md`).
- Note key invariants or guarantees that the implementation MUST uphold.

## Quick start

```bash
retrovue <noun> <verb> --flag value
```

- Provide the minimal setup steps or CLI invocations.
- Use both PowerShell (` ```powershell `) and bash (` ```bash `) blocks when the commands differ.

## Implementation outline

### Core flow

- Bullet the major steps or subsystems in execution order.

### Key dependencies

- List upstream systems (databases, registries, services).
- Cross-link to architecture docs where the relationships are explained.

## Operator workflows

- Outline common tasks with short CLI examples.
- Include expected output snippets (human-readable first, JSON second if applicable).

## Failure modes

- Enumerate known failure scenarios and mitigation steps.
- Reference incident or dev notes when available.

## Observability

- Metrics emitted, log channels, tracing identifiers.
- How to validate the component is healthy.

## Future work

- Optional. Capture planned improvements, TODOs, or follow-up contracts.

## See also

- [Sibling component](../components/<file>.md) — Short description
- [Architecture overview](../architecture/ArchitectureOverview.md) — System context
- [Glossary](../GLOSSARY.md) — Canonical terminology


