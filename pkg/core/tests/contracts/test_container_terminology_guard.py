"""
Phase 6/7/8/9: Terminology guard — fail on Collection/collection_id outside allowlisted paths.

Canonical model: Source → Container → Locator → Asset → Processor Jobs → Processor Runtime.
"Collection" and collection_id exist only in:
- Historical Alembic migrations (alembic/versions/)
- Explicitly historical docs (COLLECTION_TO_CONTAINER*, TERMINOLOGY_*, MIGRATION_NOTES_COLLECTION*)
- Stdlib/Plex/pytest line patterns (typing.Collection, .get("Collection"), pytest_collection_*)

CI must run this test; do not add production code to the allowlist.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

# Root for scanning (pkg/core); only scan project code, not .venv or site-packages
TESTS_DIR = Path(__file__).resolve().parent
CORE_ROOT = TESTS_DIR.parent.parent

# Directories to scan (relative to CORE_ROOT). Excludes .venv, __pycache__, etc.
SCAN_DIRS = ("src", "src_legacy", "tests")
# Path substrings that skip the file entirely (no scan)
SKIP_PATH_SUBSTRINGS = (".venv/", "venv/", "site-packages/", "__pycache__/", ".git/")

# Path substrings that are always excluded (historical or migration notes only)
EXCLUDED_PATH_SUBSTRINGS = (
    "alembic/versions/",
    "docs/contracts/architecture/COLLECTION_TO_CONTAINER",
    "docs/contracts/architecture/TERMINOLOGY_",
    "docs/contracts/architecture/MIGRATION_NOTES_COLLECTION",
    "test_container_terminology_guard.py",  # guard file documents policy
)

# Line content patterns: if the line matches, it is allowed (no violation)
EXCLUDED_LINE_PATTERNS = (
    re.compile(r"collections\.abc"),
    re.compile(r"from collections import"),
    re.compile(r"from typing import.*\bCollection\b"),  # typing.Collection
    re.compile(r"typing\.Collection"),
    re.compile(r"pytest_collection_modifyitems"),
    re.compile(r"pytest_ignore_collect"),
    re.compile(r"collection_path\b"),  # pytest hook param
    re.compile(r'\.get\s*\(\s*["\']Collection["\']'),  # Plex API tag
    re.compile(r"collection_tags"),
    re.compile(r"# container-migration-exclusion"),
    re.compile(r"# noqa:.*container-migration"),
    re.compile(r"deprecated.*collection|collection.*deprecated"),  # docstrings for compat tests
)

# Forbidden: word "Collection" (our entity) or identifier "collection_id" in new code.
# We scan for these and require every hit to be either excluded by path/line or in allowed list.
FORBIDDEN_PATTERN = re.compile(r"\bCollection\b|collection_id")

# Phase 9: Only historical migrations (path exclusion) and these files may contain
# Collection/collection_id. Do not add new production code; migrate to Container/container_id.
ALLOWED_TERMINOLOGY_FILES = frozenset(
    [
        "src/retrovue/domain/entities.py",  # Collection = Container alias
        "src/retrovue/cli/commands/collection.py",  # deprecated CLI group
        "src/retrovue/cli/commands/_ops/collection_ingest_service.py",  # compat wrappers + to_dict
        "src/retrovue/cli/commands/_ops/source_ingest_service.py",
        "src/retrovue/cli/commands/source.py",
        "src/retrovue/cli/main.py",  # registers collection app
        "src/retrovue/usecases/collection_enrichers.py",
        "src/retrovue/usecases/asset_enrich_stale.py",
        "src/retrovue/infra/validation.py",  # validate_collection_exists etc.
        "src/retrovue/adapters/importers/plex_importer.py",  # Plex + validate_ingestible(collection)
        "src/retrovue/adapters/importers/filesystem_importer.py",
        "src/retrovue/adapters/enrichers/interstitial_type_enricher.py",  # collection_name param
        "src/retrovue/catalog/db_asset_library.py",
        "src/retrovue/runtime/source_resolver.py",
        "src/retrovue/runtime/asset_resolver.py",
        "src/retrovue/usecases/schedule_reschedule.py",
        "src/retrovue/cli/commands/_ops/__init__.py",
        "src/retrovue/infra/canonical.py",
        "src/retrovue/domain/__init__.py",
        "src/retrovue/usecases/source_list.py",
        "src/retrovue/cli/commands/_ops/backfill_plex_artwork.py",
        # Legacy (src_legacy) — migrate or keep until legacy removed
        "src_legacy/retrovue/api/routers/ingest.py",
        "src_legacy/retrovue/content_manager/ingest_orchestrator.py",
        "src_legacy/retrovue/content_manager/source_service.py",
        "src_legacy/retrovue/cli/commands/source.py",
        "src_legacy/retrovue/cli/commands/collection.py",
        "src_legacy/retrovue/api/web/pages.py",
        # Tests: deprecated compat tests or not yet renamed
        "tests/contracts/conftest.py",  # pytest_collection_modifyitems
        "tests/conftest.py",  # pytest_ignore_collect
        "tests/contracts/test_collection_ingest_contract.py",
        "tests/contracts/test_asset_enrich_stale.py",
        "tests/contracts/test_source_ingest_service_contract.py",
        "tests/contracts/test_collection_ingest_data_contract.py",
        "tests/contracts/test_channel_purge.py",
        "tests/contracts/test_channel_reconciliation.py",
        "tests/contracts/test_processor_execution_contract.py",
        "tests/contracts/test_processor_metadata_contract.py",
        "tests/contracts/test_collection_ingest_metadata_persistence_data_contract.py",
        "tests/contracts/test_collection_ingest_payload_contract.py",
        "tests/contracts/test_interstitial_type_stamp.py",
        "tests/runtime/test_schedule_compiler.py",
        "tests/contracts/test_source_ingest_contract.py",
        "tests/domain/test_asset_resolution_contract.py",
        "tests/contracts/runtime/test_inv_epg_reads_canonical.py",
        "tests/contracts/test_collection_ingest_confidence_contract.py",
        "tests/contracts/test_filesystem_collection_discovery.py",
        "tests/contracts/test_source_discover_contract.py",
        "tests/contracts/test_source_list_data_contract.py",
        "tests/contracts/test_source_discover_data_contract.py",
        "tests/contracts/test_collection_show_contract.py",
        "tests/contracts/test_collection_wipe_contract.py",
        "tests/contracts/test_collection_list_data_contract.py",
        "tests/contracts/test_collection_list_contract.py",
        "tests/contracts/test_collection_ingest_progress_contract.py",
        "tests/contracts/test_asset_confidence_contract.py",
        "tests/contracts/test_asset_confidence_data_contract.py",
        "tests/contracts/test_collection_enricher_attach_detach_contract.py",
        "tests/contracts/cross-domain/test_source_collection_guarantees.py",
        "tests/contracts/test_collection_ingest_safety_contract.py",
        "tests/contracts/test_collection_ingest_with_real_importer_contract.py",
        "tests/contracts/test_collection_ingest_verbose_assets_contract.py",
        "tests/contracts/test_source_delete_contract.py",
        "tests/contracts/test_source_delete_data_contract.py",
        "tests/contracts/test_enricher_remove_data_contract.py",
        "tests/contracts/test_collection_update_contract.py",
        "tests/_legacy/contracts_legacy/test_collection_wipe_data_contract.py",
        "tests/_legacy/contracts_legacy/test_collection_wipe_contract.py",
        "tests/_legacy/contracts_legacy/test_sync_idempotency_contract.py",
        "tests/_legacy/cli/test_ingest_cli.py",
        "tests/catalog/test_discovery.py",
    ]
)


def _relative_path(path: Path) -> str:
    """Path relative to pkg/core."""
    try:
        return path.relative_to(CORE_ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def _is_excluded_path(rel: str) -> bool:
    if "conftest.py" in rel and ("pytest_collection" in rel or "pytest_ignore_collect" in rel):
        return False  # conftest is allowed via ALLOWED list, not path exclusion
    return any(sub in rel for sub in EXCLUDED_PATH_SUBSTRINGS)


def _is_excluded_line(line: str) -> bool:
    return any(pat.search(line) for pat in EXCLUDED_LINE_PATTERNS)


def collect_violations() -> list[tuple[str, int, str]]:
    """Return list of (relative_path, line_no, line_text) that contain forbidden terminology."""
    violations: list[tuple[str, int, str]] = []
    for scan_dir in SCAN_DIRS:
        root = CORE_ROOT / scan_dir
        if not root.exists():
            continue
        for py_path in root.rglob("*.py"):
            rel = _relative_path(py_path)
            if any(skip in rel for skip in SKIP_PATH_SUBSTRINGS):
                continue
            if _is_excluded_path(rel):
                continue
            try:
                text = py_path.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            for i, line in enumerate(text.splitlines(), start=1):
                if not FORBIDDEN_PATTERN.search(line):
                    continue
                if _is_excluded_line(line):
                    continue
                violations.append((rel, i, line.strip()))
    return violations


@pytest.mark.contract
def test_no_new_collection_terminology_outside_allowed_list():
    """
    Fail if any file outside ALLOWED_TERMINOLOGY_FILES contains Collection/collection_id.

    This guard prevents regressions. To fix: either migrate the file to Container/container_id
    or add it to ALLOWED_TERMINOLOGY_FILES (with a comment) during the compatibility window.
    Do not add new production code to the allowed list; migrate it instead.
    """
    violations = collect_violations()
    not_allowed: list[tuple[str, int, str]] = []
    for rel, line_no, line in violations:
        if rel not in ALLOWED_TERMINOLOGY_FILES:
            not_allowed.append((rel, line_no, line))

    if not not_allowed:
        return

    msg_lines = [
        "Container terminology guard: the following files contain 'Collection' or 'collection_id'",
        "but are not in ALLOWED_TERMINOLOGY_FILES. Migrate them to Container/container_id",
        "or add to the allowed list only if deprecated compat (with a comment).",
        "",
    ]
    for rel, line_no, line in sorted(not_allowed):
        msg_lines.append(f"  {rel}:{line_no}: {line[:80]}")
    pytest.fail("\n".join(msg_lines))


# Allowed doc path substrings (Phase 9: historical + paths not yet updated)
# Shrink this list as more docs are updated to Container/container_id.
DOCS_EXCLUDED_SUBSTRINGS = (
    "COLLECTION_TO_CONTAINER",
    "TERMINOLOGY_",
    "MIGRATION_NOTES_COLLECTION",
    "/archive/",
    "contracts/",
    "data/",  # domain, canonical-key; update then remove
    "overview/",
    "developer/",
    "domains/",  # repo-level docs/domains
)
DOCS_FORBIDDEN_PATTERN = re.compile(r"\bCollection\b|collection_id")


def _collect_docs_violations() -> list[tuple[str, int, str]]:
    """Scan docs (markdown) for Collection/collection_id; return violations."""
    violations: list[tuple[str, int, str]] = []
    docs_root = CORE_ROOT / "docs"
    if docs_root.exists():
        for md_path in docs_root.rglob("*.md"):
            try:
                rel = _relative_path(md_path)
            except Exception:
                rel = md_path.as_posix()
            if any(sub in rel for sub in DOCS_EXCLUDED_SUBSTRINGS):
                continue
            try:
                text = md_path.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            for i, line in enumerate(text.splitlines(), start=1):
                if not DOCS_FORBIDDEN_PATTERN.search(line):
                    continue
                violations.append((rel, i, line.strip()))
    # Repo-level docs (parent of pkg/core)
    repo_docs = CORE_ROOT.parent / "docs"
    if repo_docs.exists():
        for md_path in repo_docs.rglob("*.md"):
            rel = f"../{md_path.relative_to(CORE_ROOT.parent).as_posix()}"
            if any(sub in rel for sub in DOCS_EXCLUDED_SUBSTRINGS):
                continue
            try:
                text = md_path.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            for i, line in enumerate(text.splitlines(), start=1):
                if not DOCS_FORBIDDEN_PATTERN.search(line):
                    continue
                violations.append((rel, i, line.strip()))
    return violations


@pytest.mark.contract
def test_docs_no_collection_terminology_outside_historical():
    """
    Fail if any doc (markdown) outside historical/migration-note paths contains Collection/collection_id.

    Phase 9: Repo should read as Source → Container → Locator → Asset → ...
    Only historical refactor docs and migration notes may mention the old name.
    """
    violations = _collect_docs_violations()
    if not violations:
        return
    msg_lines = [
        "Docs terminology: the following .md files contain 'Collection' or 'collection_id'.",
        "Update them to Container/container_id, or move narrative to MIGRATION_NOTES_COLLECTION_TO_CONTAINER.md.",
        "",
    ]
    for rel, line_no, line in sorted(violations):
        msg_lines.append(f"  {rel}:{line_no}: {line[:80]}")
    pytest.fail("\n".join(msg_lines))


# Forbidden container name: must not create or reference containers named "Test Collection".
# Use "Test Container" or another name. Match only the string literal, not "Test CollectionIngest" etc.
_TEST_COLLECTION_NAME_PATTERN = re.compile(
    r'["\']Test Collection["\']'  # "Test Collection" or 'Test Collection' as literal
)
TEST_COLLECTION_PATH_EXCLUDES = (
    "COLLECTION_TO_CONTAINER",  # inventory may document "do not use"
    "test_container_terminology_guard.py",  # this guard
)


def _collect_test_collection_name_violations() -> list[tuple[str, int, str]]:
    """Find any use of the forbidden container name 'Test Collection' as a string literal."""
    violations: list[tuple[str, int, str]] = []
    for scan_dir in SCAN_DIRS:
        root = CORE_ROOT / scan_dir
        if not root.exists():
            continue
        for path in root.rglob("*.py"):
            rel = _relative_path(path)
            if any(skip in rel for skip in SKIP_PATH_SUBSTRINGS):
                continue
            if any(ex in rel for ex in TEST_COLLECTION_PATH_EXCLUDES):
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            for i, line in enumerate(text.splitlines(), start=1):
                if _TEST_COLLECTION_NAME_PATTERN.search(line):
                    violations.append((rel, i, line.strip()))
    # Also scan docs
    for docs_root in [CORE_ROOT / "docs", CORE_ROOT.parent / "docs"]:
        if not docs_root.exists():
            continue
        for path in docs_root.rglob("*.md"):
            try:
                rel = (
                    _relative_path(path)
                    if docs_root == CORE_ROOT
                    else f"../{path.relative_to(CORE_ROOT.parent).as_posix()}"
                )
            except Exception:
                rel = path.as_posix()
            if any(ex in rel for ex in TEST_COLLECTION_PATH_EXCLUDES):
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            for i, line in enumerate(text.splitlines(), start=1):
                if _TEST_COLLECTION_NAME_PATTERN.search(line):
                    violations.append((rel, i, line.strip()))
    return violations


@pytest.mark.contract
def test_no_container_named_test_collection():
    """
    Fail if any code or doc creates or references a container named 'Test Collection'.

    Use 'Test Container' or another name. Do not reintroduce 'Test Collection'.
    """
    violations = _collect_test_collection_name_violations()
    if not violations:
        return
    msg_lines = [
        "Forbidden container name 'Test Collection' found. Use 'Test Container' (or another name).",
        "Do not create containers with this name.",
        "",
    ]
    for rel, line_no, line in sorted(violations):
        msg_lines.append(f"  {rel}:{line_no}: {line[:80]}")
    pytest.fail("\n".join(msg_lines))
