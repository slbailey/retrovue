"""Contract test: Proto stubs must live in server/src/retrovue/proto/.

Invariant: Production code must not depend on legacy/ paths for proto stubs.
The canonical location for Python gRPC stubs is server/src/retrovue/proto/.

This test enforces that:
1. Proto stubs exist at the canonical location (server/src/retrovue/proto/).
2. No production code references legacy/ proto paths.
3. No production code references the old server/core/proto/ path.
"""

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
CANONICAL_PROTO_DIR = REPO_ROOT / "server" / "src" / "retrovue" / "proto"

REQUIRED_STUBS = [
    "__init__.py",
    "playout_pb2.py",
    "playout_pb2_grpc.py",
    "execution_evidence_v1_pb2.py",
    "execution_evidence_v1_pb2_grpc.py",
]


class TestProtoStubCanonicalLocation:
    """Proto stubs must live in server/src/retrovue/proto/."""

    def test_canonical_directory_exists(self):
        assert CANONICAL_PROTO_DIR.is_dir(), (
            f"Canonical proto directory missing: {CANONICAL_PROTO_DIR}"
        )

    @pytest.mark.parametrize("stub", REQUIRED_STUBS)
    def test_stub_exists_at_canonical_location(self, stub: str):
        stub_path = CANONICAL_PROTO_DIR / stub
        assert stub_path.exists(), (
            f"Proto stub missing at canonical location: {stub_path}"
        )

    def test_no_legacy_proto_path_in_production_code(self):
        """No production .py file should reference legacy/ proto paths."""
        prod_dir = REPO_ROOT / "server" / "src"
        violations = []
        for py_file in prod_dir.rglob("*.py"):
            content = py_file.read_text()
            if "legacy" in content and "proto" in content:
                # Skip if it's only in a comment about history
                for i, line in enumerate(content.splitlines(), 1):
                    stripped = line.strip()
                    if "legacy" in stripped and "proto" in stripped:
                        if not stripped.startswith("#"):
                            violations.append(f"{py_file.relative_to(REPO_ROOT)}:{i}: {stripped}")
        assert not violations, (
            "Production code references legacy proto paths:\n"
            + "\n".join(violations)
        )

    def test_no_old_core_proto_path_in_production_code(self):
        """No production .py file should reference server/core/proto/."""
        prod_dir = REPO_ROOT / "server" / "src"
        violations = []
        for py_file in prod_dir.rglob("*.py"):
            content = py_file.read_text()
            for i, line in enumerate(content.splitlines(), 1):
                stripped = line.strip()
                if "core" in stripped and "proto" in stripped and "retrovue" in stripped:
                    # Allow references to the new canonical path server/src/retrovue/proto
                    if '"core"' in stripped or "'core'" in stripped or "core/proto" in stripped:
                        if not stripped.startswith("#"):
                            violations.append(f"{py_file.relative_to(REPO_ROOT)}:{i}: {stripped}")
        assert not violations, (
            "Production code references old core/proto path:\n"
            + "\n".join(violations)
        )
