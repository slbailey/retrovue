# Dev notes — <topic or incident>

_Related: [Component README](../components/<component>.md) • [Architecture doc](../architecture/<doc>.md)_

## Purpose
Summarize the reason for this dev note (bug triage, refactor rationale, incident root cause, etc.).

## Metadata

- **Date:** YYYY-MM-DD
- **Author(s):** @github-handle
- **Status:** draft | active | resolved
- **Scope:** feature | incident | refactor | investigation

## Summary

Provide a concise narrative (3–5 sentences) describing what changed or what you are investigating.

## Trigger

- Describe the event, bug, or request that initiated this work.
- Link to GitHub issues, incidents, or external tickets.

## Findings

- Bullet the key observations, experiments, and data points.
- Reference log files, dashboards, or test runs as needed.

## Decisions

| Decision | Rationale | Owner | Date |
| --- | --- | --- | --- |
| Example | Why we chose this path | @owner | YYYY-MM-DD |

- Note any decisions that require follow-up approval.

## Implementation notes

- Detail code changes, migrations, scripts, or manual steps performed.
- Include CLI commands in fenced blocks (bash and PowerShell variants when they differ).

## Risks and mitigations

- Identify risks that remain and how we mitigate them in the short term.
- Call out monitoring or alerting updates required.

## Follow-up tasks

- [ ] Task one (owner, due date)
- [ ] Task two

## Impact on contracts

- List contract docs or tests touched.
- Note whether exit codes, outputs, or invariants changed.

## See also

- [Linked incident](../developer/incidents/<file>.md) — Optional description
- [Change request](../developer/rfcs/<file>.md) — Optional description


