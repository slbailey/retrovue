"""Utility helpers for contract tests.

Provides shared assertion utilities that keep contract tests concise and
focused on validating contract-required structure instead of exact
representations.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def assert_contains_fields(obj: Mapping[str, Any], expected: Mapping[str, Any]) -> None:
    """Assert that *obj* contains the keys and values provided in *expected*.

    A value of ``...`` indicates that only the presence of the key is enforced,
    without checking the concrete value. Nested dictionaries are supported by
    recursively validating their contents when both the expected value and the
    actual value are mappings.
    """

    for key, expected_value in expected.items():
        assert key in obj, f"Missing expected field: {key}"

        actual_value = obj[key]

        if expected_value is ...:
            continue

        if isinstance(expected_value, Mapping) and isinstance(actual_value, Mapping):
            assert_contains_fields(actual_value, expected_value)
            continue

        assert actual_value == expected_value, (
            f"Field '{key}' expected {expected_value!r} but found {actual_value!r}"
        )

