from __future__ import annotations

from pathlib import Path


FORBIDDEN_PATTERNS = (
    "datetime.now(",
    "datetime.utcnow(",
    "time.time(",
)

SOURCE_ROOTS = (
    Path("/opt/retrovue/server/src/retrovue/catalog"),
    Path("/opt/retrovue/server/src/retrovue/usecases"),
    Path("/opt/retrovue/server/src/retrovue/web/api"),
)


def test_catalog_usecases_and_api_do_not_read_global_wall_clock() -> None:
    offenders: list[str] = []
    for root in SOURCE_ROOTS:
        for path in sorted(root.rglob("*.py")):
            text = path.read_text()
            for pattern in FORBIDDEN_PATTERNS:
                if pattern in text:
                    offenders.append(f"{path}: {pattern}")
    assert offenders == []
