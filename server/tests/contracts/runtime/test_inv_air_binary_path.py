"""
Contract test: AIR binary search path must reference runtime/build/, not pkg/air/.

After RETA-227 restructured pkg/air/ into runtime/, all production code that
locates the AIR binary must use runtime/build/retrovue_air (relative to repo root),
not the legacy pkg/air/build/ path.

Invariant: No production module may contain a path referencing 'pkg/air'.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
PRODUCTION_SRC = REPO_ROOT / "server" / "src" / "retrovue"

# Directories that are NOT production code (dev tools, tests, etc.)
_EXCLUDED_DIRS = {"dev", "__pycache__"}

# Matches path-division patterns like: / "pkg" / "air" or Path("pkg") / "air"
# Also matches plain string literals like "pkg/air"
_PKG_AIR_PATTERNS = [
    re.compile(r'"pkg"\s*/\s*"air"'),       # "pkg" / "air" (Path division)
    re.compile(r"'pkg'\s*/\s*'air'"),        # 'pkg' / 'air' (Path division)
    re.compile(r"""["']pkg/air"""),           # "pkg/air..." (string literal)
    re.compile(r"""["']pkg\\\\air"""),        # "pkg\\air..." (Windows-style)
]


def _production_python_files() -> list[Path]:
    """Collect all .py files under server/src/retrovue excluding dev/test dirs."""
    results = []
    for p in PRODUCTION_SRC.rglob("*.py"):
        parts = p.relative_to(PRODUCTION_SRC).parts
        if any(part in _EXCLUDED_DIRS for part in parts):
            continue
        results.append(p)
    return results


class TestNoLegacyPkgAirPaths:
    """Production code must not reference the removed pkg/air/ directory."""

    @pytest.mark.parametrize(
        "py_file",
        _production_python_files(),
        ids=lambda p: str(p.relative_to(PRODUCTION_SRC)),
    )
    def test_no_pkg_air_reference(self, py_file: Path) -> None:
        """No production code should build or contain a pkg/air path."""
        source = py_file.read_text(encoding="utf-8")
        for lineno, line in enumerate(source.splitlines(), 1):
            # Skip comments
            stripped = line.lstrip()
            if stripped.startswith("#"):
                continue
            for pattern in _PKG_AIR_PATTERNS:
                assert not pattern.search(line), (
                    f"{py_file.relative_to(PRODUCTION_SRC)}:{lineno} "
                    f"contains legacy pkg/air path reference: {line.strip()!r}"
                )
