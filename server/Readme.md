# RetroVue Core

RetroVue Core is the **contract-first** Python system for ingesting content, defining scheduling intent, and orchestrating runtime playout (in collaboration with `retrovue-air`).

## Start here

- **Docs index**: `docs/README.md`
- **Repo review + roadmap (“what’s next”)**: `docs/overview/RepoReviewAndRoadmap.md`
- **Architecture mental model**: `docs/architecture/ArchitectureOverview.md`
- **Contracts index (authoritative behavior)**: `docs/contracts/resources/README.md`

## Key policy (read this before contributing)

- **Contract-first workflow**: Domain → Contract → Test → Implement.
- **Contracts describe outcomes** (what must be true), not implementation details.
- **CLI is a development/test harness**, not a presentation-stable UI:
  - Human-readable output is not stable.
  - Prefer **`--json`** for stable assertions and automation.

## Quick start (local dev)

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
retrovue --help
pytest tests/contracts -q
```

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
retrovue --help
pytest tests/contracts -q
```

## Repo layout (high level)

- `src/retrovue/` — Core app code (domain/usecases/cli/infra/runtime).
- `docs/` — Canonical documentation (architecture/domain/contracts/operator/developer).
- `tests/contracts/` — Contract tests (preferred enforcement surface).

## Related repositories

- **C++ playout engine**: `https://github.com/slbailey/retrovue-air`
- **Shared doc standards**: `https://github.com/slbailey/retrovue-doc-standards`

# RetroVue Core

RetroVue Core is the **contract-first** Python system for ingesting content, defining scheduling intent, and orchestrating runtime playout (in collaboration with `retrovue-air`).

## Start here

- **Docs index**: `docs/README.md`
- **Repo review + roadmap (“what’s next”)**: `docs/overview/RepoReviewAndRoadmap.md`
- **Architecture mental model**: `docs/architecture/ArchitectureOverview.md`
- **Contracts index (authoritative behavior)**: `docs/contracts/resources/README.md`

## Project philosophy (the important bits)

- **Contract-first workflow**: Domain → Contract → Test → Implement.
- **Outcome-focused contracts**: contracts define **what must be true**, not how it’s implemented.
- **CLI is a development/test harness**, not a presentation-stable UI:
  - Human-readable output is not stable.
  - Prefer **`--json`** for stable assertions and automation.

## Quick start (local dev)

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
retrovue --help
pytest tests/contracts -q
```

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
retrovue --help
pytest tests/contracts -q
```

## Repo layout (high level)

- `src/retrovue/` — Core app code (domain/usecases/cli/infra/runtime).
- `docs/` — Canonical documentation (architecture/domain/contracts/operator/developer).
- `tests/contracts/` — Contract tests (preferred enforcement surface).

## Related repositories

- **C++ playout engine**: `https://github.com/slbailey/retrovue-air`
- **Shared doc standards**: `https://github.com/slbailey/retrovue-doc-standards`
