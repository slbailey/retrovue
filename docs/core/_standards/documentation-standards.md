# Documentation standards

## Purpose

Define the canonical tone, structure, and formatting rules for all Retrovue documentation in `docs/`, component READMEs, and inline architecture notes across retrovue-core and retrovue-air.

## Voice and tone

- Write in present tense and active voice.
- Keep paragraphs to 1–3 concise sentences.
- Be declarative and operational; avoid marketing language or rhetorical questions.
- Emojis are reserved for public-facing overview docs (top-level README). Internal docs stay emoji-free.
- Use second-person sparingly; prefer descriptive narration (“The CLI returns…”) over imperatives.

## Heading and section order

- Use sentence case for headings (`## Purpose`, not `## PURPOSE`).
- Each doc starts with `## Purpose`. Follow with `## Scope` or `## Audience` when additional framing is needed.
- Domain/runtime docs adopt this baseline order:
  1. Purpose
  2. Core model / scope
  3. Contract / interface
  4. Execution model
  5. Failure / fallback behavior
  6. Operator workflows (when applicable)
  7. Naming rules
  8. See also
- Contract docs extend the model with: Command shape → Safety expectations → Output formats → Exit codes → Data effects → Behavioral rules → Data rules → Test coverage → Error cases → Examples → See also.
- Architecture docs include Purpose → Context → Design drivers → Responsibilities → Data/interfaces → Operational flow (with Mermaid diagram) → Failure/fallback → Deployment/scaling → Security → Testing → Open questions → See also.

## Cross-linking pattern

- Add an optional `_Related: [...]_` breadcrumb line above the H1 when obvious neighbor docs exist.
- End with a `## See also` section listing the most relevant related docs, each with a short annotation.
- Prefer relative links to keep navigation valid across clones and forks.

## Formatting

- Wrap lines near 100 characters to keep diffs legible.
- Use bullet lists for unordered sets, numbered lists only for ordered sequences.
- Highlight literal commands, flags, paths, and slugs with backticks.
- Code fences specify the language (` ```bash`, ` ```powershell`, ` ```python`).
- Present CLI examples in both bash and PowerShell when syntax differs.
- Tables are acceptable for structured comparisons but keep them narrow and scannable.
- Use **MUST**, **SHOULD**, **MAY** for normative statements; avoid ambiguous phrasing.
- Include “Status” sections when documenting experimental or deprecated features.

## Terminology

- Treat canonical nouns as proper names: Channel, Collection, Source, ChannelManager, MasterClock, PlaylogEvent, DiscoveredItem.
- Maintain existing naming conventions (kebab-case slugs, snake_case CLI flags).
- Add new vocabulary to `docs/GLOSSARY.md`; link to it from the introducing document.
- Refer to CLI commands as `retrovue <noun> <verb>` and include representative examples.

## Documentation workflow

- Draft or update documentation before implementing code changes.
- Update contract docs and associated tests in the same change set.
- Annotate deprecated docs with a top note and link to the replacement.
- For diagrams, embed Mermaid code blocks or link to the `.mmd` source checked into the repo.
- Use the templates in `docs/_standards/` (README, architecture, dev notes, changelog) for new files.

## Review checklist

- Purpose section reflects current behavior.
- Headings follow sentence case and recommended order.
- Links are relative and valid.
- Examples mirror actual CLI/API output.
- Contract docs match behavior enforced by tests.
- `_Related` breadcrumb (when applicable) and `See also` section included.
- Style choices align with this standard and the AI methodology.

## See also

- [AI assistant methodology](ai-assistant-methodology.md)
- [Repository conventions](repository-conventions.md)
- [Test methodology](test-methodology.md)


