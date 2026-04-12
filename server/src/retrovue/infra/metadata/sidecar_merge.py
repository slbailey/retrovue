from collections.abc import Sequence
from typing import Any

_SCOPE_PRIORITY: dict[str, int] = {"collection": 0, "series": 1, "file": 2}


def _scope_rank_dict(sc: dict[str, Any]) -> int:
    meta = sc.get("_meta") if isinstance(sc, dict) else None
    scope = (meta or {}).get("scope") or "file"
    return _SCOPE_PRIORITY.get(str(scope).lower(), 2)


def _merge_lists(high: list[Any] | None, low: list[Any] | None) -> list[Any] | None:
    if high is None and low is None:
        return None
    if high is None:
        return list(low or [])
    if low is None:
        return list(high)
    merged: list[Any] = []
    for item in high:
        if item not in merged:
            merged.append(item)
    for item in low:
        if item not in merged:
            merged.append(item)
    return merged


def _deep_merge_dict(
    overlay: dict[str, Any],
    base: dict[str, Any],
    authoritative_keys: Sequence[str],
) -> dict[str, Any]:
    """Deep-merge two sidecar dicts.

    - Scalars: non-null overlay values overwrite base
    - Lists: prefix-merge + dedupe unless key is authoritative (then replace)
    - Dicts: recurse
    - `_meta` handled by caller
    """
    result: dict[str, Any] = dict(base)
    for key, ov in overlay.items():
        if key == "_meta":
            continue
        if key in authoritative_keys and key in overlay:
            result[key] = ov
            continue
        bv = result.get(key)
        if isinstance(ov, list):
            result[key] = _merge_lists(ov, bv if isinstance(bv, list) else None)
        elif isinstance(ov, dict):
            if isinstance(bv, dict):
                result[key] = _deep_merge_dict(ov, bv, authoritative_keys)
            else:
                result[key] = dict(ov)
        else:
            if ov is not None:
                result[key] = ov
    return result


def merge_sidecars(sidecars: list[dict[str, Any]]) -> dict[str, Any]:
    """Merge multiple sidecar dicts per scope and authoritative rules.

    Merge order: collection (lowest) → series → file (highest).
    - Scalar fields: overwrite when overlay provides a non-null value.
    - Array fields: if key is listed in overlay._meta.authoritative_fields, replace; otherwise,
      prefix-merge + dedupe (overlay first).
    - `_meta.authoritative_fields` in the result is the union of authoritative fields across all
      scopes.
    Returns the merged sidecar dict with `_meta` taken from the highest priority overlay, except
    that `authoritative_fields` is unioned.
    """
    if not sidecars:
        raise ValueError("merge_sidecars requires at least one sidecar")

    ordered = sorted(sidecars, key=_scope_rank_dict)

    merged = dict(ordered[0])
    for sc in ordered[1:]:
        auth: list[str] = []
        meta = sc.get("_meta") if isinstance(sc, dict) else None
        if isinstance(meta, dict):
            auth = meta.get("authoritative_fields") or []
        merged = _deep_merge_dict(sc, merged, auth)

    # Build final _meta: highest priority sidecar's meta, union authoritative_fields
    highest_meta = (ordered[-1].get("_meta") or {}) if isinstance(ordered[-1], dict) else {}
    union_auth: list[str] = []
    seen = set()
    for sc in ordered:
        fields = ((sc.get("_meta") or {}).get("authoritative_fields") or []) if isinstance(sc, dict) else []
        for f in fields:
            if f not in seen:
                seen.add(f)
                union_auth.append(f)
    final_meta = dict(highest_meta)
    if union_auth:
        final_meta["authoritative_fields"] = union_auth
    if final_meta:
        merged["_meta"] = final_meta

    return merged



