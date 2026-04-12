"""
Contract tests for INV-NO-HARDCODED-SECRETS-001.

No git-tracked source file may contain literal secret material
(API keys, authentication tokens, passwords in connection strings).

Test IDs: SECRETS-SCAN-001, SECRETS-SCAN-002, SECRETS-SCAN-003
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]  # server/tests/contracts -> repo root

# Extensions to scan — matches the invariant's "Deterministic Testability" section
SOURCE_EXTENSIONS = {".py", ".yaml", ".yml", ".json", ".sh", ".toml", ".cfg", ".ini"}

# Directories containing vendored / third-party code (not our responsibility)
EXCLUDED_PREFIXES = (
    "runtime/third_party/",
    "server/.venv/",
    ".venv/",
    "third_party/",
)

# Files that legitimately reference credential *parameters* (not literal values)
# e.g. gRPC stubs with channel_credentials=None, enricher templates with api_key as param name
EXCLUDED_FILES = {
    # Auto-generated gRPC stubs
    "server/src/retrovue/proto/execution_evidence_v1_pb2_grpc.py",
    "server/src/retrovue/proto/playout_pb2_grpc.py",
    # Enricher/importer templates and base classes (parameter names, not literal values)
    "server/src/retrovue/adapters/enrichers/enricher_template.py",
    "server/src/retrovue/adapters/enrichers/base.py",
    "server/src/retrovue/adapters/importers/importer_template.py",
    "server/src/retrovue/adapters/importers/base.py",
    "server/src/retrovue/adapters/importers/plex_importer.py",
    # CLI commands that accept --token / --api-key as flags (no literals)
    "server/src/retrovue/cli/commands/enricher.py",
    "server/src/retrovue/cli/commands/source.py",
    "server/src/retrovue/cli/commands/collection.py",
    "server/src/retrovue/cli/commands/_ops/backfill_plex_artwork.py",
    # Legacy CLI (parameter references only)
    "server/src_legacy/retrovue/cli/commands/plex.py",
    "server/src_legacy/retrovue/cli/commands/source.py",
    "server/src_legacy/retrovue/content_manager/ingest_orchestrator.py",
    "server/src_legacy/retrovue/content_manager/source_service.py",
    "server/src_legacy/retrovue/api/main.py",
    "server/src_legacy/retrovue/api/web/pages.py",
    # Settings module (reads from env, declares field names)
    "server/src/retrovue/infra/settings.py",
    # Logging module (redaction patterns, not secrets)
    "server/src/retrovue/infra/logging.py",
    # Test fixtures with fake tokens
    "server/tests/contracts/plex/test_plex_artwork.py",
    "server/src/retrovue/adapters/registry.py",
    # This test file itself
    "server/tests/contracts/test_inv_no_hardcoded_secrets.py",
    # GitHub CI (test-only postgres password)
    "server/.github/workflows/test-workflow.yml",
    # Alembic config (commented-out example DSN)
    "server/alembic.ini",
    # Legacy test fixtures with test:test placeholder creds (skipped)
    "server/tests/_legacy/test_compliance_reporting.py",
    "server/tests/_legacy/test_identity_model.py",
    # Contract conftest (documentation example in docstring)
    "server/tests/contracts/conftest.py",
    # DB check scripts (env var fallbacks with placeholder creds / redaction utility)
    "scripts/core/check_db.py",
    "scripts/core/check_localhost_db.py",
    "scripts/core/test_db_connection.py",
}


def _git_tracked_source_files() -> list[str]:
    """Return all git-tracked files with source extensions."""
    result = subprocess.run(
        ["git", "ls-files"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    files = []
    for f in result.stdout.strip().splitlines():
        if any(f.startswith(prefix) for prefix in EXCLUDED_PREFIXES):
            continue
        if f in EXCLUDED_FILES:
            continue
        if Path(f).suffix in SOURCE_EXTENSIONS:
            files.append(f)
    return files


# ── Pattern families ──────────────────────────────────────────────────

# SECRETS-SCAN-001: API keys (Google/YouTube AIza prefix, generic api_key = "...")
API_KEY_PATTERNS = [
    re.compile(r"AIza[0-9A-Za-z_-]{35}"),                       # Google API key
    re.compile(r"""(?:api_key|API_KEY)\s*=\s*["'][A-Za-z0-9_-]{16,}["']"""),  # Generic hardcoded key
]

# SECRETS-SCAN-002: Passwords in DSNs / connection strings
PASSWORD_PATTERNS = [
    re.compile(r"password\s*=\s*[A-Za-z0-9_!@#$%^&*]{4,}(?:\s|\"|\')"),  # DSN password=<literal>
    re.compile(r"://[^:]+:[^@\s]{4,}@"),                        # URI scheme://user:pass@host
]

# SECRETS-SCAN-003: Auth tokens (Plex, GitHub, Slack, generic)
TOKEN_PATTERNS = [
    re.compile(r"""(?:PLEX_TOKEN|plex_token)\s*=\s*["'][A-Za-z0-9_-]{10,}["']"""),
    re.compile(r"ghp_[A-Za-z0-9]{36}"),                         # GitHub PAT
    re.compile(r"gho_[A-Za-z0-9]{36}"),                         # GitHub OAuth
    re.compile(r"xox[bpas]-[A-Za-z0-9-]+"),                     # Slack token
]


def _scan_files(patterns: list[re.Pattern]) -> list[str]:
    """Return list of 'file:line: <match>' for any pattern hit in tracked source files."""
    violations = []
    for relpath in _git_tracked_source_files():
        abspath = REPO_ROOT / relpath
        try:
            content = abspath.read_text(errors="replace")
        except OSError:
            continue
        for i, line in enumerate(content.splitlines(), 1):
            for pat in patterns:
                if pat.search(line):
                    # Redact the actual secret in the violation message
                    violations.append(f"{relpath}:{i}")
                    break  # one violation per line is enough
    return violations


class TestInvNoHardcodedSecrets001:
    """INV-NO-HARDCODED-SECRETS-001 — No secret material in git-tracked source files."""

    def test_secrets_scan_001_no_hardcoded_api_keys(self):
        """SECRETS-SCAN-001: No hardcoded API keys in tracked files."""
        violations = _scan_files(API_KEY_PATTERNS)
        assert violations == [], (
            f"INV-NO-HARDCODED-SECRETS-001 violated: hardcoded API keys found:\n"
            + "\n".join(f"  {v}" for v in violations)
        )

    def test_secrets_scan_002_no_hardcoded_passwords(self):
        """SECRETS-SCAN-002: No hardcoded passwords in tracked DSNs."""
        violations = _scan_files(PASSWORD_PATTERNS)
        assert violations == [], (
            f"INV-NO-HARDCODED-SECRETS-001 violated: hardcoded passwords found:\n"
            + "\n".join(f"  {v}" for v in violations)
        )

    def test_secrets_scan_003_no_hardcoded_tokens(self):
        """SECRETS-SCAN-003: No hardcoded auth tokens in tracked files."""
        violations = _scan_files(TOKEN_PATTERNS)
        assert violations == [], (
            f"INV-NO-HARDCODED-SECRETS-001 violated: hardcoded tokens found:\n"
            + "\n".join(f"  {v}" for v in violations)
        )
