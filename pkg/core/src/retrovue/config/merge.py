"""
Deep merge logic per the Configuration Resolution contract.

Rules (docs/contracts/configuration_resolution.md §3):
- Dictionaries: recursively merged
- Scalars: channel overrides default
- Lists: fully replaced (NOT merged)
- Null: explicit null overrides default (opt-out mechanism)
- Type validation: mismatches rejected

Rules (§6):
- Unknown keys within governed domains: rejected
- Type mismatches: rejected
- Structural mismatches (scalar vs dict): rejected
"""

from __future__ import annotations

from types import MappingProxyType
from typing import Any


class ConfigMergeError(Exception):
    """Raised when a merge rule is violated."""


class UnknownKeyError(ConfigMergeError):
    """Raised when a channel config contains unknown keys in a governed domain."""


class TypeMismatchError(ConfigMergeError):
    """Raised when a channel override has an incompatible type."""


class StructuralMismatchError(ConfigMergeError):
    """Raised when a scalar conflicts with a dict (or vice versa)."""


# Type compatibility matrix (default_type -> set of accepted override types).
# int overriding float is accepted (widening).
# float overriding int is NOT accepted.
_TYPE_COMPAT: dict[type, set[type]] = {
    int: {int},
    float: {int, float},
    str: {str},
    bool: {bool},
}


def _check_type_compat(
    path: str,
    default_val: Any,
    override_val: Any,
) -> None:
    """Validate that override_val's type is compatible with default_val's type.

    Raises TypeMismatchError on incompatible types.
    Raises StructuralMismatchError when scalar vs dict conflicts.
    """
    # Null override is always accepted (opt-out mechanism, §3.4).
    if override_val is None:
        return

    default_type = type(default_val)
    override_type = type(override_val)

    # Structural mismatch: dict vs scalar.
    default_is_dict = isinstance(default_val, (dict, MappingProxyType))
    override_is_dict = isinstance(override_val, (dict, MappingProxyType))

    if default_is_dict and not override_is_dict:
        raise StructuralMismatchError(
            f"Structural mismatch at '{path}': default is a dict but override is "
            f"{override_type.__name__}"
        )
    if not default_is_dict and override_is_dict:
        raise StructuralMismatchError(
            f"Structural mismatch at '{path}': default is {default_type.__name__} "
            f"but override is a dict"
        )

    # Both dicts or both lists: structural match, merge/replace handles it.
    if default_is_dict and override_is_dict:
        return
    if isinstance(default_val, (list, tuple)) and isinstance(override_val, (list, tuple)):
        return

    # Scalar type compatibility check.
    accepted = _TYPE_COMPAT.get(default_type)
    if accepted is not None and override_type not in accepted:
        raise TypeMismatchError(
            f"Type mismatch at '{path}': default is {default_type.__name__}, "
            f"override is {override_type.__name__}"
        )


def deep_merge(
    defaults: dict[str, Any] | MappingProxyType[str, Any],
    overrides: dict[str, Any],
    *,
    governed_keys: frozenset[str] | None = None,
    _path: str = "",
    _validate: bool = True,
) -> dict[str, Any]:
    """Recursively merge overrides into defaults.

    Returns a new mutable dict (caller is responsible for freezing).

    Args:
        defaults: The global defaults (may be frozen MappingProxyType).
        overrides: Channel-level overrides.
        governed_keys: Top-level keys governed by defaults.yaml.
            Unknown keys within these domains are rejected.
            Keys outside these domains pass through.
        _path: Internal — dotted path for error messages.
        _validate: Whether to perform type/key validation.

    Returns:
        Merged dict (mutable).

    Raises:
        UnknownKeyError: Unknown key in a governed domain.
        TypeMismatchError: Incompatible type override.
        StructuralMismatchError: Scalar/dict conflict.
    """
    result: dict[str, Any] = {}

    # Copy all defaults into the result.
    for key, default_val in defaults.items():
        child_path = f"{_path}.{key}" if _path else key

        if key in overrides:
            override_val = overrides[key]

            if override_val is None:
                # §3.4: explicit null clears the default.
                result[key] = None

            elif isinstance(default_val, (dict, MappingProxyType)) and isinstance(override_val, dict):
                # §3.1: recursive dict merge.
                result[key] = deep_merge(
                    default_val,
                    override_val,
                    governed_keys=governed_keys,
                    _path=child_path,
                    _validate=_validate,
                )
            elif isinstance(default_val, (list, tuple)) and isinstance(override_val, list):
                # §3.3: list replacement.
                result[key] = list(override_val)
            else:
                # §3.2: scalar override.
                if _validate:
                    _check_type_compat(child_path, default_val, override_val)
                result[key] = override_val
        else:
            # Key not in overrides: inherit default.
            # Unfreeze MappingProxyType/tuple back to mutable for the result.
            result[key] = _to_mutable(default_val)

    # Pass-through keys: keys in overrides that don't exist in defaults.
    for key, override_val in overrides.items():
        if key in defaults:
            continue  # Already handled above.

        child_path = f"{_path}.{key}" if _path else key

        if _validate and governed_keys and _path == "":
            # At the top level: reject unknown keys in governed domains?
            # No — unknown top-level keys are pass-through (pools, programs, etc.).
            # We only reject unknown keys WITHIN governed domains.
            pass

        if _validate and governed_keys and _in_governed_domain(_path, governed_keys):
            raise UnknownKeyError(
                f"Unknown key '{child_path}' in governed domain. "
                f"This key does not exist in defaults.yaml."
            )

        result[key] = _to_mutable(override_val) if isinstance(override_val, (dict, MappingProxyType)) else override_val

    return result


def _in_governed_domain(path: str, governed_keys: frozenset[str]) -> bool:
    """Return True if the given dotted path is inside a governed domain.

    A path is governed if its root segment (top-level key) is in governed_keys.
    The empty string (top level itself) is NOT governed — unknown top-level
    keys are pass-through.
    """
    if not path:
        return False
    root = path.split(".")[0]
    return root in governed_keys


def _to_mutable(val: Any) -> Any:
    """Recursively convert frozen types back to mutable equivalents."""
    if isinstance(val, MappingProxyType):
        return {k: _to_mutable(v) for k, v in val.items()}
    if isinstance(val, tuple):
        return [_to_mutable(item) for item in val]
    return val


__all__ = [
    "ConfigMergeError",
    "UnknownKeyError",
    "TypeMismatchError",
    "StructuralMismatchError",
    "deep_merge",
]
