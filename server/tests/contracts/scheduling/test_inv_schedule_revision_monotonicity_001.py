"""
Contract tests for INV-SCHEDULE-REVISION-MONOTONICITY-001.

After a reader observes R_new as active, no stale cache may serve future
editorial schedule from superseded R_old. Caches keyed by time alone
must carry revision identity or be invalidated on publish.

Tier 1: invariant document is present and specifies non-optional rules.
Tier 2/3: add simulated publish + read ordering once cache versioning lands.
"""

from __future__ import annotations

from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[4]
_INV_PATH = (
    _REPO_ROOT
    / "docs"
    / "contracts"
    / "invariants"
    / "core"
    / "scheduling"
    / "INV-SCHEDULE-REVISION-MONOTONICITY-001.md"
)


@pytest.mark.contract
class TestInvScheduleRevisionMonotonicity001:
    """INV-SCHEDULE-REVISION-MONOTONICITY-001 contract tests."""

    def test_invariant_file_defines_monotonicity_and_cache_rules(self) -> None:
        text = _INV_PATH.read_text(encoding="utf-8")
        assert "INV-SCHEDULE-REVISION-MONOTONICITY-001" in text
        assert "revision_id" in text
        assert "invalidate" in text.lower()
        assert "superseded" in text.lower()
