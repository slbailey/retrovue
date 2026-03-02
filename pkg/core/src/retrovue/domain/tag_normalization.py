"""Tag normalization primitives.

Single source of truth for tag normalization used by both the ingest pipeline
and the operator CLI. See: INV-ASSET-TAG-PERSISTENCE-001, AssetTaggingContract.md B-1/D-2.
"""

from __future__ import annotations

import re


def normalize_tag(raw: str) -> str:
    """Normalize a single tag: strip, lowercase, collapse internal whitespace.

    Examples:
        normalize_tag("  Classic ") == "classic"
        normalize_tag("HBO Max")    == "hbo max"
        normalize_tag("A  B")       == "a b"
    """
    return re.sub(r"\s+", " ", raw.strip()).lower()


def normalize_tag_set(tags: list[str]) -> list[str]:
    """Normalize a list of tags: apply normalize_tag, deduplicate, sort.

    Empty or whitespace-only tags are silently discarded.

    Examples:
        normalize_tag_set(["HBO", "hbo", "  HBO  "]) == ["hbo"]
        normalize_tag_set(["zebra", "apple"])         == ["apple", "zebra"]
    """
    return sorted({normalize_tag(t) for t in tags if t.strip()})
