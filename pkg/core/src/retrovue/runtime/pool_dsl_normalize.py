"""
Normalize declarative pool definitions for CatalogAssetResolver / StubAssetResolver.

Canonical YAML uses select.where (docs/contracts/dsl_consolidation_plan.md).
The catalog query layer still consumes flat ``match`` criteria; this module
bridges the two shapes at register_pools time.
"""

from __future__ import annotations

from typing import Any


_TAG_SET_OPERATORS = {"contains_all", "contains_any", "excludes_any"}


def _where_atom(field: str, spec: Any) -> Any | dict[str, Any]:
    """Turn one field's select clause into match-compatible value(s).

    For tags with set operators (contains_all, contains_any, excludes_any),
    returns a dict ``{"_tag_ops": True, ...}`` so the caller can split into
    separate match keys.  All three may coexist on the same field.
    """
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
    # Tag set operators — any subset of {contains_all, contains_any, excludes_any}
    if keys and keys <= _TAG_SET_OPERATORS:
        if field != "tags":
            raise ValueError(
                f"POOL-DSL: {', '.join(sorted(keys))} "
                f"{'is' if len(keys) == 1 else 'are'} only valid under select.where.tags"
            )
        return {"_tag_ops": True, **{k: spec[k] for k in keys}}
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
        result = _where_atom(field, spec)
        # Tag set operators return a dict with _tag_ops sentinel
        if isinstance(result, dict) and result.get("_tag_ops") and field == "tags":
            if "contains_all" in result:
                match["tags"] = result["contains_all"]
            if "contains_any" in result:
                match["tags_any"] = result["contains_any"]
            if "excludes_any" in result:
                match["tags_exclude"] = result["excludes_any"]
        else:
            match[field] = result
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
