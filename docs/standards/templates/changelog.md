# Retrovue changelog

_Related: [Test methodology](test-methodology.md) • [Release checklist](../developer/ReleaseChecklist.md)_

## Purpose
Explain the changes captured in this changelog and why they matter for contract-first releases.

Use this template for repo-wide changelog files (`CHANGELOG.md`). Follow [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) semantics, adapted to Retrovue’s contract-first workflow.

## [Unreleased]

### Added

- Outline new features or capabilities.
- Link to contract docs and tests that codify the behavior.

### Changed

- Note behavior changes, migrations, or updated defaults.
- Mention affected CLI commands or APIs.

### Deprecated

- Call out features scheduled for removal, including timeline and mitigation path.

### Removed

- List features or commands removed in this cycle and reference migration guides.

### Fixed

- Summarize bug fixes with references to incidents, tests, or PRs.

### Security

- Record security fixes, CVE references, and mitigation steps.

---

## [YYYY-MM-DD] - vX.Y.Z

### Added

- …

### Changed

- …

### Deprecated

- …

### Removed

- …

### Fixed

- …

### Security

- …

## Release checklist

- [ ] Contracts updated and merged prior to release.
- [ ] All contract tests in `tests/contracts` pass locally (`pytest tests/contracts -vv`).
- [ ] Database migrations applied (`alembic upgrade head`).
- [ ] Docs regenerated where automation exists (e.g., CLI help snapshots).
- [ ] Version bumped in `pyproject.toml` and package metadata.
- [ ] Release tag created and signed.
- [ ] Changelog entry copied to downstream repos if the change spans multiple projects.

