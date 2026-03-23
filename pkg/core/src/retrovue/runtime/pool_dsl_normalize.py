"""
Normalize declarative pool definitions for CatalogAssetResolver / StubAssetResolver.

Canonical YAML uses select.where (docs/contracts/dsl_consolidation_plan.md).
The catalog query layer still consumes flat ``match`` criteria; this module
bridges the two shapes at register_pools time.
"""

from __future__ import annotations

from typing import Any


def _where_atom(field: str, spec: Any) -> Any:
    """Turn one field's select clause into a match-compatible value."""
    if spec is None:
        return None
    if not isinstance(spec, dict):
        return spec

    keys = set(spec.keys())
    if keys == {"eq"}:
        return spec["eq"]
    if keys == {"in"}:
        vals = spec["in"]
        if field == "rating":
            if not isinstance(vals, list):
                vals = [vals]
            return {"include": list(vals)}
        if field == "genres":
            raise ValueError(
                "POOL-DSL: select.where.genres.in is not supported for pools; "
                "use field 'genre' with eq (substring match) or split pools."
            )
        return vals
    if keys == {"contains_all"}:
        if field != "tags":
            raise ValueError(
                "POOL-DSL: contains_all is only valid under select.where.tags"
            )
        return spec["contains_all"]
    if keys & {"gte", "lte"}:
        raise ValueError(
            f"POOL-DSL: gte/lte not supported for pool field {field!r} "
            "(static select.where only)."
        )
    raise ValueError(f"POOL-DSL: unsupported select.where clause for {field}: {spec!r}")


def select_where_to_match(where: dict[str, Any]) -> dict[str, Any]:
    """Convert select.where mapping to legacy match dict for catalog query()."""
    match: dict[str, Any] = {}
    for field, spec in where.items():
        if spec is None:
            continue
        match[field] = _where_atom(field, spec)
    return match


def normalize_pool_definition(defn: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of defn with match populated from select.where when present."""
    out = dict(defn)
    sel = out.get("select")
    if isinstance(sel, dict) and "where" in sel:
        where = sel["where"]
        if not isinstance(where, dict):
            raise ValueError("POOL-DSL: select.where must be a mapping")
        out["match"] = select_where_to_match(where)
        del out["select"]
    return out


def normalize_pools(pools: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {name: normalize_pool_definition(defn) for name, defn in pools.items()}
