"""
Contract tests for filesystem collection discovery (B-11).

Tests that FilesystemImporter.list_collections() enumerates immediate
subdirectories of the source base path, returning one collection per
subdirectory — enforcing the Source (1) → (N) Collections cardinality
established in Collection.md.

Contract: docs/contracts/resources/SourceDiscoverContract.md
Rule: B-11
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from retrovue.adapters.importers.filesystem_importer import FilesystemImporter


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_tree(tmp_path: Path, dirs: list[str], files: dict[str, list[str]] | None = None) -> Path:
    """Create a directory tree under tmp_path and return the base path.

    Args:
        tmp_path: pytest tmp_path fixture
        dirs: list of subdirectory names to create
        files: optional mapping of dir_name -> [filenames] to create inside dirs
    """
    base = tmp_path / "source_root"
    base.mkdir()
    for d in dirs:
        (base / d).mkdir()
    if files:
        for d, fnames in files.items():
            for fname in fnames:
                (base / d / fname).touch()
    return base


def _importer(base_path: Path) -> FilesystemImporter:
    return FilesystemImporter(
        source_name="test-source",
        root_paths=[str(base_path)],
    )


# ---------------------------------------------------------------------------
# B-11: Filesystem collection discovery
# ---------------------------------------------------------------------------

class TestFilesystemCollectionDiscovery:
    """B-11: Filesystem source collection discovery from subdirectories."""

    def test_one_collection_per_subdirectory(self, tmp_path: Path):
        """Each immediate subdirectory becomes a separate collection."""
        base = _make_tree(tmp_path, ["bumpers", "commercials", "promos"])
        imp = _importer(base)

        collections = imp.list_collections(source_config={})

        names = {c["name"] for c in collections}
        assert names == {"bumpers", "commercials", "promos"}
        assert len(collections) == 3

    def test_returns_multiple_collections_not_one(self, tmp_path: Path):
        """Enforces Source (1) → (N) Collections — never collapses to 1."""
        base = _make_tree(tmp_path, ["a", "b", "c", "d"])
        imp = _importer(base)

        collections = imp.list_collections(source_config={})

        assert len(collections) > 1, (
            "FilesystemImporter must return one collection per subdirectory, "
            "not a single flattened collection"
        )

    def test_no_subdirectories_returns_empty(self, tmp_path: Path):
        """A source with no subdirectories discovers zero collections."""
        base = _make_tree(tmp_path, [])
        # Put a file at the top level — should be ignored
        (base / "loose_file.mp4").touch()
        imp = _importer(base)

        collections = imp.list_collections(source_config={})

        assert collections == []

    def test_files_at_top_level_ignored(self, tmp_path: Path):
        """Non-directory entries at the top level are not collections."""
        base = _make_tree(tmp_path, ["real_collection"])
        (base / "readme.txt").touch()
        (base / "playlist.m3u").touch()
        imp = _importer(base)

        collections = imp.list_collections(source_config={})

        names = {c["name"] for c in collections}
        assert names == {"real_collection"}

    def test_does_not_recurse_beyond_first_level(self, tmp_path: Path):
        """Discovery only looks at immediate children, not nested subdirs."""
        base = _make_tree(tmp_path, ["commercials"])
        nested = base / "commercials" / "90s"
        nested.mkdir()
        imp = _importer(base)

        collections = imp.list_collections(source_config={})

        names = {c["name"] for c in collections}
        assert "90s" not in names
        assert names == {"commercials"}

    def test_empty_subdirectory_still_returned(self, tmp_path: Path):
        """Empty subdirectories are valid collections (B-11)."""
        base = _make_tree(tmp_path, ["empty_collection"])
        imp = _importer(base)

        collections = imp.list_collections(source_config={})

        assert len(collections) == 1
        assert collections[0]["name"] == "empty_collection"

    def test_symlink_directory_included(self, tmp_path: Path):
        """Symlinks resolving to directories are included (B-11)."""
        base = _make_tree(tmp_path, ["real_dir"])
        target = tmp_path / "external_dir"
        target.mkdir()
        link = base / "linked_collection"
        link.symlink_to(target)
        imp = _importer(base)

        collections = imp.list_collections(source_config={})

        names = {c["name"] for c in collections}
        assert "linked_collection" in names
        assert "real_dir" in names

    def test_each_collection_has_stable_external_id(self, tmp_path: Path):
        """Each collection must have a unique, stable external_id."""
        base = _make_tree(tmp_path, ["bumpers", "commercials"])
        imp = _importer(base)

        collections = imp.list_collections(source_config={})

        ids = [c["external_id"] for c in collections]
        assert len(ids) == len(set(ids)), "external_ids must be unique"

        # Run again — ids must be the same (stable)
        collections2 = imp.list_collections(source_config={})
        ids2 = [c["external_id"] for c in collections2]
        assert sorted(ids) == sorted(ids2), "external_ids must be stable across calls"

    def test_collection_has_required_fields(self, tmp_path: Path):
        """Each collection dict must contain the fields expected by source_discover."""
        base = _make_tree(tmp_path, ["promos"])
        imp = _importer(base)

        collections = imp.list_collections(source_config={})

        assert len(collections) == 1
        c = collections[0]
        assert "external_id" in c
        assert "name" in c
        assert isinstance(c["external_id"], str)
        assert isinstance(c["name"], str)

    def test_collection_name_matches_directory_name(self, tmp_path: Path):
        """Collection name must be the directory basename, not a full path."""
        base = _make_tree(tmp_path, ["station_ids"])
        imp = _importer(base)

        collections = imp.list_collections(source_config={})

        assert collections[0]["name"] == "station_ids"

    def test_hidden_directories_excluded_by_default(self, tmp_path: Path):
        """Directories starting with '.' should be excluded by default."""
        base = _make_tree(tmp_path, ["visible", ".hidden"])
        imp = _importer(base)

        collections = imp.list_collections(source_config={})

        names = {c["name"] for c in collections}
        assert "visible" in names
        assert ".hidden" not in names

    def test_interstitials_layout_discovers_all_types(self, tmp_path: Path):
        """Simulate /mnt/data/Interstitials layout — all subdirs become collections."""
        subdirs = [
            "bumpers", "commercials", "intros", "oddities", "promos",
            "psas", "shortform", "station_ids", "teasers", "trailers",
        ]
        base = _make_tree(tmp_path, subdirs)
        imp = _importer(base)

        collections = imp.list_collections(source_config={})

        discovered_names = {c["name"] for c in collections}
        assert discovered_names == set(subdirs)
