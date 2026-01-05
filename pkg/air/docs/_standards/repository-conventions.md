# Repository conventions

## Purpose

Document the canonical directory structure, naming rules, and cross-repo alignment for Retrovue projects so teams maintain architectural consistency between retrovue-core, retrovue-air, and future siblings.

## Top-level layout

- `src/retrovue/` — Primary application code.
  - `domain/` — SQLAlchemy models, enums, and invariants (no orchestration logic).
  - `usecases/` — Function-first application layer; mediates between CLI and domain.
  - `cli/commands/` — Typer/Click wiring, argument parsing, output formatting per contract.
  - `infra/` — Database/session factories, configuration, logging, cross-cutting utilities.
  - `runtime/` — Playout, scheduling, ffmpeg orchestration, MasterClock, ChannelManager.
- `docs/` — Architecture, domain, contracts, operator, developer guides, templates.
- `tests/` — Contract tests, fixtures, and supporting suites (mirrors CLI nouns).
- `alembic/` — Database migrations and env configuration.
- `scripts/` — One-off operational scripts (validated before inclusion).
- `src_legacy/` — Quarantine for deprecated modules; new code must not import from here.
- `docs/_standards/` — Shared standards (this directory) synchronized across repos.
- `build/` — Generated artifacts, CMake cache, and proto outputs (checked in only when contracts require it).

## File placement rules

- No new top-level directories without explicit approval.
- Avoid creating generic `services/` or `repositories/`; use existing layers or define private helpers within the file.
- Usecases accept explicit parameters and sessions/unit-of-work, never call `commit()` inside helper utilities.
- CLI commands call usecases and format output; they do not enforce business logic.
- Runtime code does not import from CLI or tests.
- Documentation changes live under `docs/`; templates stay in `docs/_standards/`.
- Native modules follow the structure described in **C++ layout** below; do not mix public headers with sources.

## C++ layout (native modules like retrovue-air)

- Public headers live under `include/retrovue/<module>/`. File names use PascalCase or descriptive snake_case that mirrors the class (`FrameRingBuffer.h`, `MetricsExporter.h`).
- Implementation files live under `src/<module>/` with matching stem names (`FrameRingBuffer.cpp` pairs with `FrameRingBuffer.h`).
- Namespaces mirror the directory path, e.g. `retrovue::buffer::FrameRingBuffer`.
- Avoid flat headers directly under `include/`; every public artifact belongs to a module directory.
- Internal-only headers stay beside their `.cpp` files in `src/`.
- Generated proto sources land under `build/generated/retrovue/` (or the build system’s equivalent) and are not manually edited.
- Shared telemetry helpers live under `src/telemetry/` and expose Prometheus-compatible exporters; tests consume them via dedicated fixtures, not ad-hoc copies.
- Keep tooling scripts (`scripts/`) language-agnostic; C++-specific helpers (`generate_stubs.py`, build wrappers) live there and document required toolchains.

## Naming conventions

- Modules and packages use snake_case (`channel_manager.py`).
- Classes and SQLAlchemy models use PascalCase.
- CLI commands follow `retrovue <noun> <verb>` with singular nouns (`channel`, `source`, `collection`).
- Database tables are pluralized snake_case (`channels`, `schedule_plans`).
- Environment variables use screaming snake case (`RETROVUE_DATABASE_URL`).
- Migrations follow timestamp or descriptive slug formats already in use (keep alembic autogeneration consistent).
- C++ classes follow PascalCase, namespaces are lowercase with `::` separators matching directory structure, and Prometheus metrics names use `retrovue_<component>_<metric>`.

## Versioning and compatibility

- Semantic versioning applies to packaged artifacts; document release notes in `CHANGELOG.md`.
- Migrations are idempotent per environment; do not modify existing versions—add new revisions instead.
- Contract changes require corresponding updates to tests and docs before code merges.
- Keep `docs/_standards/` synchronized across sibling repos; note repo-specific exceptions inline.

## Cross-repo expectations

- `docs/contracts/` remains the authoritative record for CLI behavior in every repo.
- Shared terminology and tone come from `documentation-standards.md`.
- AI collaboration process is identical across repos (see `ai-assistant-methodology.md`).
- When introducing new subsystems, document them under `docs/architecture` or `docs/domain` before implementation.
- Sibling repos may extend these conventions but must not contradict them without updating this document.

## Legacy boundaries

- `src_legacy/`, `src/retrovue/app/`, `src/retrovue/content_manager/`, and `src/retrovue/schedule_manager/` are historical; do not add new code there.
- If old modules still supply behavior, plan a migration path that creates new usecases/CLI commands and retires the legacy path.
- Do not import legacy modules into new code unless performing a controlled migration.

## See also

- [Documentation standards](documentation-standards.md)
- [Test methodology](test-methodology.md)
- [AI assistant methodology](ai-assistant-methodology.md)


