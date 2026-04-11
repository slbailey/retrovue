"""Tag normalization and canonicalization primitives.

Single source of truth for tag normalization used by both the ingest pipeline
and the operator CLI. See: INV-ASSET-TAG-PERSISTENCE-001, INV-TAG-CANONICAL-FORM-001,
tag_canonical_form.md.
"""

from __future__ import annotations

import re

# Controlled vocabulary of recognized namespaces (tag_canonical_form.md §B).
_VALID_NAMESPACES = frozenset({"tag", "network", "genre", "rating"})

# Legacy colon-prefix → canonical namespace mapping (§C-1).
_LEGACY_PREFIX_MAP: dict[str, str] = {
    "TAG": "tag",
    "NETWORK": "network",
    "GENRE": "genre",
    "RATING": "rating",
}


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


def canonicalize_tag(raw: str) -> str:
    """Convert any tag form to canonical ``namespace.value`` form.

    Handles three input forms (tag_canonical_form.md §C):
    - Already canonical: ``tag.hbo`` → ``tag.hbo``
    - Legacy colon-prefixed: ``TAG:hbo`` → ``tag.hbo``
    - Plain: ``hbo`` → ``tag.hbo``

    The value part is normalized (strip, lowercase, whitespace collapse).
    Migration is idempotent (INV-TAG-MIGRATION-IDEMPOTENT-001).

    Raises ValueError for unrecognized namespace prefixes (§B-1).
    """
    raw = raw.strip()

    # Legacy colon-prefixed format: TAG:hbo, NETWORK:cbs
    if ":" in raw:
        prefix, value = raw.split(":", 1)
        ns = _LEGACY_PREFIX_MAP.get(prefix.upper())
        if ns is None:
            raise ValueError(
                f"Unrecognized legacy tag prefix {prefix!r}. "
                f"Valid prefixes: {sorted(_LEGACY_PREFIX_MAP)}"
            )
        return f"{ns}.{normalize_tag(value)}"

    # Already canonical: namespace.value
    if "." in raw:
        ns, value = raw.split(".", 1)
        ns_lower = ns.lower()
        if ns_lower in _VALID_NAMESPACES:
            return f"{ns_lower}.{normalize_tag(value)}"
        # Dot in value but not a recognized namespace — treat as plain tag
        # (values with dots are forbidden per A-4, but be defensive for migration)
        return f"tag.{normalize_tag(raw)}"

    # Plain tag: hbo → tag.hbo
    return f"tag.{normalize_tag(raw)}"


def strip_tag_namespace(tag: str) -> str:
    """Strip the namespace prefix from a tag, returning the value part.

    Handles both canonical dot form and legacy colon form.

    Examples:
        strip_tag_namespace("tag.hbo")           == "hbo"
        strip_tag_namespace("network.cbs")       == "cbs"
        strip_tag_namespace("TAG:hbo")           == "hbo"
        strip_tag_namespace("NETWORK:cbs")       == "cbs"
        strip_tag_namespace("hbo")               == "hbo"
    """
    if "." in tag:
        ns, value = tag.split(".", 1)
        if ns.lower() in _VALID_NAMESPACES:
            return value
    if ":" in tag:
        return tag.split(":", 1)[1]
    return tag


def expand_tag_match_set(asset_tags: set[str]) -> set[str]:
    """Expand a set of asset tags to include all historical query forms.

    During the transition period (tag_canonical_form.md §D), pool DSL and
    catalog resolver queries may use any of:
    - Canonical: ``tag.hbo``
    - Colon-prefixed: ``TAG:hbo`` / ``tag:hbo``
    - Plain: ``hbo``

    This function expands each tag in the input set to all matching forms
    so that queries in any format will match.

    Examples:
        expand_tag_match_set({"tag.hbo"}) == {"tag.hbo", "tag:hbo", "hbo"}
        expand_tag_match_set({"TAG:hbo"}) == {"tag:hbo", "tag.hbo", "hbo"}
        expand_tag_match_set({"hbo"})     == {"hbo", "tag.hbo", "tag:hbo"}
    """
    expanded: set[str] = set()
    for tag in asset_tags:
        low = tag.lower()
        expanded.add(low)

        # Determine namespace and value from any format
        ns: str | None = None
        value: str | None = None

        if "." in low:
            parts = low.split(".", 1)
            if parts[0] in _VALID_NAMESPACES:
                ns, value = parts[0], parts[1]
        if ns is None and ":" in low:
            parts = low.split(":", 1)
            prefix_ns = _LEGACY_PREFIX_MAP.get(parts[0].upper())
            if prefix_ns:
                ns, value = prefix_ns, parts[1]

        if ns and value:
            # Add all three forms
            expanded.add(f"{ns}.{value}")   # canonical: tag.hbo
            expanded.add(f"{ns}:{value}")   # legacy colon: tag:hbo
            expanded.add(value)              # plain: hbo
        else:
            # Plain tag with no namespace — expand to canonical + colon forms
            plain = strip_tag_namespace(low)
            expanded.add(plain)
            expanded.add(f"tag.{plain}")
            expanded.add(f"tag:{plain}")

    return expanded
