#!/usr/bin/env python3
"""Test JSON parsing."""

import json
import sys

# Test the exact string the user provided
test_cases = [
    '{"duration_max_minutes": 30, "tags": ["sitcom"]}',
    "{'duration_max_minutes': 30, 'tags': ['sitcom']}",
]

for test_json in test_cases:
    print(f"Testing: {test_json}")
    try:
        parsed = json.loads(test_json)
        print(f"  ✓ Valid JSON: {parsed}")
    except json.JSONDecodeError as e:
        print(f"  ✗ Invalid JSON: {e}")

