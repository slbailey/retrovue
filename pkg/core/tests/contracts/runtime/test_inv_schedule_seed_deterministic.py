"""
Contract tests for INV-SCHEDULE-SEED-DETERMINISTIC-001.

Channel-specific seeds MUST be deterministic across process lifetimes.
Same channel_id -> same seed, always. Seeds MUST use hashlib, not hash().
"""

from __future__ import annotations

import ast
import hashlib
from pathlib import Path

import pytest

from retrovue.runtime.schedule_compiler import channel_seed


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SRC_ROOT = Path(__file__).parents[3] / "src" / "retrovue"

# Files that previously used abs(hash(channel_id)) % 100000
SEED_CALLSITE_FILES = [
    SRC_ROOT / "runtime" / "dsl_schedule_service.py",
    SRC_ROOT / "runtime" / "program_director.py",
    SRC_ROOT / "web" / "api" / "epg.py",
]


def _find_hash_calls_in_file(filepath: Path) -> list[str]:
    """Use AST to find calls to hash() in a Python file.

    Returns a list of descriptions of hash() calls found.
    """
    source = filepath.read_text()
    tree = ast.parse(source, filename=str(filepath))
    violations = []

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            # Match: hash(...)
            if isinstance(func, ast.Name) and func.id == "hash":
                line = getattr(node, "lineno", "?")
                violations.append(
                    f"{filepath.name}:{line} — hash() call found"
                )
    return violations


# ---------------------------------------------------------------------------
# Contract Tests
# ---------------------------------------------------------------------------


class TestInvScheduleSeedDeterministic001:
    """INV-SCHEDULE-SEED-DETERMINISTIC-001 contract tests."""

    def test_seed_is_deterministic(self):
        """channel_seed('showtime-cinema') called twice returns same value."""
        s1 = channel_seed("showtime-cinema")
        s2 = channel_seed("showtime-cinema")
        assert s1 == s2, f"Seeds differ: {s1} != {s2}"

    def test_seed_matches_hashlib(self):
        """Result equals int(hashlib.sha256(b'showtime-cinema').hexdigest(), 16) % 100000."""
        expected = int(hashlib.sha256(b"showtime-cinema").hexdigest(), 16) % 100000
        actual = channel_seed("showtime-cinema")
        assert actual == expected, f"channel_seed returned {actual}, expected {expected}"

    def test_different_channels_different_seeds(self):
        """Two different channel_ids produce different seeds."""
        s1 = channel_seed("showtime-cinema")
        s2 = channel_seed("retro-prime")
        assert s1 != s2, (
            f"Different channels produced same seed: "
            f"showtime-cinema={s1}, retro-prime={s2}"
        )

    def test_no_builtin_hash_in_seed_callsites(self):
        """No hash() calls exist in dsl_schedule_service.py, program_director.py,
        or epg.py. All channel seed derivation MUST use channel_seed()."""
        all_violations = []
        for filepath in SEED_CALLSITE_FILES:
            if filepath.exists():
                violations = _find_hash_calls_in_file(filepath)
                all_violations.extend(violations)

        assert all_violations == [], (
            f"Found hash() calls in seed callsite files:\n"
            + "\n".join(f"  - {v}" for v in all_violations)
        )
