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


def strip_tag_namespace(tag: str) -> str:
    """Strip the CATEGORY: namespace prefix from a tag, returning the value part.

    If the tag has no colon, returns the tag unchanged (already a plain value).

    Examples:
        strip_tag_namespace("TAG:hbo")           == "hbo"
        strip_tag_namespace("NETWORK:cbs")       == "cbs"
        strip_tag_namespace("hbo")               == "hbo"
        strip_tag_namespace("TAG:presentation")  == "presentation"
    """
    if ":" in tag:
        return tag.split(":", 1)[1]
    return tag


def expand_tag_match_set(asset_tags: set[str]) -> set[str]:
    """Expand a set of asset tags to include both namespaced and stripped forms.

    This enables backward-compatible matching: DSL configs using plain tags
    (e.g. "hbo") match DB tags stored with namespaces (e.g. "TAG:hbo").

    The returned set contains every original tag plus its stripped value.
    All values are lowercased.

    Examples:
        expand_tag_match_set({"TAG:hbo", "NETWORK:cbs"}) == {"tag:hbo", "hbo", "network:cbs", "cbs"}
        expand_tag_match_set({"hbo"})                     == {"hbo"}
    """
    expanded = set()
    for tag in asset_tags:
        low = tag.lower()
        expanded.add(low)
        stripped = strip_tag_namespace(low)
        if stripped != low:
            expanded.add(stripped)
    return expanded
