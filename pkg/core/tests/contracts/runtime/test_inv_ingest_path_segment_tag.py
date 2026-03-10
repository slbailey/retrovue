"""Contract tests for INV-INGEST-PATH-SEGMENT-TAG-001.

When a filesystem source collection is configured with tag_from_path_segments=True,
every directory component between the configured root and the file's parent
(inclusive, not including root itself) MUST be emitted as a normalized tag.
No component may be silently dropped.

Rules:
1. A 2-deep path yields exactly 2 tags.
2. A 3-deep path yields exactly 3 tags.
3. Directory names are normalized (strip, lower, single-space).
4. Root dir itself is NOT a tag; file name is NOT a tag.
5. With flag disabled (default), existing interstitial inference runs instead.
"""

import tempfile
from pathlib import Path

import pytest

from retrovue.adapters.importers.filesystem_importer import FilesystemImporter


def _importer(root: str, tag_from_path_segments: bool = True) -> FilesystemImporter:
    return FilesystemImporter(
        source_name="test",
        root_paths=[root],
        tag_from_path_segments=tag_from_path_segments,
    )


def _tag_labels(importer: FilesystemImporter, file_path: Path) -> list[str]:
    """Extract tag: prefixed labels from importer path-segment inference."""
    labels = importer._infer_tags_from_path_segments(file_path)
    return [lbl for lbl in labels if lbl.startswith("tag:")]


# ---------------------------------------------------------------------------
# Rule 1: 2-deep path → exactly 2 tags
# ---------------------------------------------------------------------------

class TestRuleAllSegmentsEmitted:
    """Rule 1: All path segment components between root and file parent are emitted."""

    # Tier: 2 | Scheduling logic invariant
    def test_two_deep_path_yields_two_tags(self, tmp_path):
        """
        INV-INGEST-PATH-SEGMENT-TAG-001 Rule 1:
        root/HBO/1982/intro.mp4 must yield tags ['tag:hbo', 'tag:1982'].
        """
        root = tmp_path
        file_path = tmp_path / "HBO" / "1982" / "intro.mp4"
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.touch()

        imp = _importer(str(root))
        labels = _tag_labels(imp, file_path)
        tag_values = {lbl[len("tag:"):] for lbl in labels}

        assert tag_values == {"hbo", "1982"}, (
            f"INV-INGEST-PATH-SEGMENT-TAG-001 Rule 1: "
            f"Expected {{'hbo', '1982'}}, got {tag_values}"
        )

    # Tier: 2 | Scheduling logic invariant
    def test_single_deep_path_yields_one_tag(self, tmp_path):
        """
        INV-INGEST-PATH-SEGMENT-TAG-001 Rule 1:
        root/HBO/intro.mp4 must yield exactly one tag: 'hbo'.
        """
        root = tmp_path
        file_path = tmp_path / "HBO" / "intro.mp4"
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.touch()

        imp = _importer(str(root))
        labels = _tag_labels(imp, file_path)
        tag_values = {lbl[len("tag:"):] for lbl in labels}

        assert tag_values == {"hbo"}, (
            f"INV-INGEST-PATH-SEGMENT-TAG-001 Rule 1: "
            f"Expected {{'hbo'}}, got {tag_values}"
        )


# ---------------------------------------------------------------------------
# Rule 2: No segment dropped — 3-deep path yields exactly 3 tags
# ---------------------------------------------------------------------------

class TestRuleNoSegmentDropped:
    """Rule 2: Every intermediate directory component must produce a tag."""

    # Tier: 2 | Scheduling logic invariant
    def test_three_deep_path_yields_three_tags(self, tmp_path):
        """
        INV-INGEST-PATH-SEGMENT-TAG-001 Rule 2:
        root/A/B/C/file.mp4 must yield exactly 3 tags.
        """
        root = tmp_path
        file_path = tmp_path / "A" / "B" / "C" / "file.mp4"
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.touch()

        imp = _importer(str(root))
        labels = _tag_labels(imp, file_path)
        tag_values = {lbl[len("tag:"):] for lbl in labels}

        assert len(tag_values) == 3, (
            f"INV-INGEST-PATH-SEGMENT-TAG-001 Rule 2: "
            f"Expected 3 tags, got {len(tag_values)}: {tag_values}"
        )
        assert tag_values == {"a", "b", "c"}, (
            f"INV-INGEST-PATH-SEGMENT-TAG-001 Rule 2: "
            f"Expected {{'a','b','c'}}, got {tag_values}"
        )


# ---------------------------------------------------------------------------
# Rule 3: Normalization — dir names are stripped, lowercased, single-spaced
# ---------------------------------------------------------------------------

class TestRuleNormalization:
    """Rule 3: Directory names must be normalized before becoming tags."""

    # Tier: 2 | Scheduling logic invariant
    def test_uppercase_dir_name_normalized(self, tmp_path):
        """
        INV-INGEST-PATH-SEGMENT-TAG-001 Rule 3:
        Directory 'HBO' must yield tag 'hbo' (lowercased).
        """
        root = tmp_path
        file_path = tmp_path / "HBO" / "file.mp4"
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.touch()

        imp = _importer(str(root))
        labels = _tag_labels(imp, file_path)
        tag_values = {lbl[len("tag:"):] for lbl in labels}

        assert "hbo" in tag_values, (
            f"INV-INGEST-PATH-SEGMENT-TAG-001 Rule 3: 'HBO' must normalize to 'hbo', got {tag_values}"
        )
        assert "HBO" not in tag_values, (
            f"INV-INGEST-PATH-SEGMENT-TAG-001 Rule 3: un-normalized 'HBO' must not appear"
        )

    # Tier: 2 | Scheduling logic invariant
    def test_whitespace_in_dir_name_normalized(self, tmp_path):
        """
        INV-INGEST-PATH-SEGMENT-TAG-001 Rule 3:
        Directory 'HBO Max' (with space) must yield tag 'hbo max' (single space, lowercase).
        """
        root = tmp_path
        file_path = tmp_path / "HBO Max" / "file.mp4"
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.touch()

        imp = _importer(str(root))
        labels = _tag_labels(imp, file_path)
        tag_values = {lbl[len("tag:"):] for lbl in labels}

        assert "hbo max" in tag_values, (
            f"INV-INGEST-PATH-SEGMENT-TAG-001 Rule 3: 'HBO Max' must normalize to 'hbo max', got {tag_values}"
        )


# ---------------------------------------------------------------------------
# Rule 4: Root dir itself and file name are NOT tags
# ---------------------------------------------------------------------------

class TestRuleOnlyBetweenRootAndParent:
    """Rule 4: Root directory and file stem must not appear as tags."""

    # Tier: 2 | Scheduling logic invariant
    def test_root_dir_not_a_tag(self, tmp_path):
        """
        INV-INGEST-PATH-SEGMENT-TAG-001 Rule 4:
        The root path's own directory name must NOT appear as a tag.
        """
        root = tmp_path  # e.g., /tmp/pytest-xyz/test_root_dir_not_a_tag0
        file_path = tmp_path / "SubDir" / "file.mp4"
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.touch()

        imp = _importer(str(root))
        labels = _tag_labels(imp, file_path)
        tag_values = {lbl[len("tag:"):] for lbl in labels}

        root_name = root.name.lower()
        assert root_name not in tag_values, (
            f"INV-INGEST-PATH-SEGMENT-TAG-001 Rule 4: "
            f"Root dir name '{root_name}' must not appear as a tag, got {tag_values}"
        )

    # Tier: 2 | Scheduling logic invariant
    def test_file_name_not_a_tag(self, tmp_path):
        """
        INV-INGEST-PATH-SEGMENT-TAG-001 Rule 4:
        The file name (stem) must NOT appear as a tag.
        """
        root = tmp_path
        file_path = tmp_path / "HBO" / "intro.mp4"
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.touch()

        imp = _importer(str(root))
        labels = _tag_labels(imp, file_path)
        tag_values = {lbl[len("tag:"):] for lbl in labels}

        assert "intro" not in tag_values, (
            f"INV-INGEST-PATH-SEGMENT-TAG-001 Rule 4: file stem 'intro' must not appear as a tag"
        )
        assert "intro.mp4" not in tag_values, (
            f"INV-INGEST-PATH-SEGMENT-TAG-001 Rule 4: filename 'intro.mp4' must not appear as a tag"
        )


# ---------------------------------------------------------------------------
# Rule 5: Flag is False by default — interstitial inference runs instead
# ---------------------------------------------------------------------------

class TestRuleDisabledByDefault:
    """Rule 5: Without tag_from_path_segments=True, the flag is inactive."""

    # Tier: 2 | Scheduling logic invariant
    def test_flag_defaults_to_false(self):
        """
        INV-INGEST-PATH-SEGMENT-TAG-001 Rule 5:
        FilesystemImporter constructed without tag_from_path_segments
        must have the attribute set to False.
        """
        imp = FilesystemImporter(source_name="test", root_paths=["/tmp"])
        assert hasattr(imp, "tag_from_path_segments"), (
            "INV-INGEST-PATH-SEGMENT-TAG-001 Rule 5: "
            "FilesystemImporter must expose tag_from_path_segments attribute"
        )
        assert imp.tag_from_path_segments is False, (
            f"INV-INGEST-PATH-SEGMENT-TAG-001 Rule 5: "
            f"tag_from_path_segments must default to False, got {imp.tag_from_path_segments!r}"
        )

    # Tier: 2 | Scheduling logic invariant
    def test_method_exists(self):
        """
        INV-INGEST-PATH-SEGMENT-TAG-001 Rule 5:
        _infer_tags_from_path_segments must exist on FilesystemImporter.
        """
        imp = FilesystemImporter(source_name="test", root_paths=["/tmp"])
        assert hasattr(imp, "_infer_tags_from_path_segments"), (
            "INV-INGEST-PATH-SEGMENT-TAG-001: "
            "FilesystemImporter must have _infer_tags_from_path_segments method"
        )
