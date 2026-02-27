#!/usr/bin/env python3
"""
Audit invariant docs: ensure each has a "## Required Tests" section
with at least one test path, and that all listed test files exist.
Exit 0 if all valid, 1 if any failure.
Run from repo root.
"""
from __future__ import annotations

import os
import re
import sys


def find_invariant_docs(root: str) -> list[str]:
    """Return sorted paths to all .md files under docs/contracts/invariants/."""
    out = []
    base = os.path.join(root, "docs", "contracts", "invariants")
    if not os.path.isdir(base):
        return out
    for dirpath, _dirnames, filenames in os.walk(base):
        for name in filenames:
            if name.endswith(".md"):
                out.append(os.path.join(dirpath, name))
    return sorted(out)


# Paths must match: pkg/*/tests/**/*.py, pkg/*/tests/**/*.cpp, tests/**/*.py, tests/**/*.cpp
_PATH_RE = re.compile(
    r"^(?:pkg/[^/]+/tests/.+\.(?:py|cpp)|tests/.+\.(?:py|cpp))$"
)


def extract_test_paths_from_section(section_text: str) -> list[str]:
    """
    From the "## Required Tests" section text, extract file paths that match
    the allowed patterns. Paths are taken from backtick-enclosed content.
    """
    paths = []
    # Match backtick-enclosed content; take only the path part (no trailing parenthetical)
    for m in re.finditer(r"`([^`]+)`", section_text):
        candidate = m.group(1).strip()
        # Optional trailing " (comment)" — path is the part before that
        if " (" in candidate:
            candidate = candidate.split(" (", 1)[0].strip()
        if _PATH_RE.match(candidate):
            paths.append(candidate)
    return paths


def get_required_tests_section(content: str) -> str | None:
    """
    Return the body of the "## Required Tests" section (up to next ## or end).
    Return None if the section is missing.
    """
    match = re.search(r"\n## Required Tests\s*\n(.*?)(?=\n## |\Z)", content, re.DOTALL)
    if not match:
        return None
    return match.group(1).strip()


def audit_one(invariant_path: str, repo_root: str) -> list[str]:
    """
    Audit a single invariant .md file. Return list of problem descriptions
    (empty if valid).
    """
    problems = []
    try:
        with open(invariant_path, "r", encoding="utf-8") as f:
            content = f.read()
    except OSError as e:
        problems.append(f"Cannot read file: {e}")
        return problems

    section = get_required_tests_section(content)
    if section is None:
        problems.append("Missing '## Required Tests' section")
        return problems

    test_paths = extract_test_paths_from_section(section)
    if not test_paths:
        problems.append("No test paths found in Required Tests section")
        return problems

    for path in test_paths:
        full = os.path.join(repo_root, path)
        if not os.path.isfile(full):
            problems.append(f"Test path does not exist: {path}")

    return problems


def main() -> int:
    repo_root = os.path.abspath(os.curdir)
    invariant_docs = find_invariant_docs(repo_root)
    failures = []

    for inv_path in invariant_docs:
        rel = os.path.relpath(inv_path, repo_root)
        problems = audit_one(inv_path, repo_root)
        for problem in problems:
            failures.append((rel, problem))

    if failures:
        for rel, problem in failures:
            print(f"{rel}: {problem}")
        return 1
    print("All invariants valid.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
