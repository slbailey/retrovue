"""Contract tests for ``retrovue collection list`` behavior rules (B-#)."""

# CONTRACT: docs/contracts/resources/CollectionListContract.md
# PURPOSE: enforce B-0 through B-12 behavior for the collection list CLI command

from __future__ import annotations

import json
import uuid
from collections.abc import Mapping
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from retrovue.cli.main import app

from .utils import assert_contains_fields


def _make_collection(
    collection_id: str,
    *,
    source_id=None,
    external_id: str = "plex-1",
    name: str = "TV Shows",
    sync_enabled: bool = True,
    ingestible: bool = True,
    config: Mapping[str, object] | None = None,
):
    return SimpleNamespace(
        uuid=uuid.UUID(collection_id),
        source_id=source_id,
        external_id=external_id,
        name=name,
        sync_enabled=sync_enabled,
        ingestible=ingestible,
        config=config or {"plex_section_ref": "plex://1"},
    )


def _make_path_mapping(*, plex_path: str = "/media/tv", local_path: str = ""):
    return SimpleNamespace(plex_path=plex_path, local_path=local_path)


def _mock_db_session(mock_session):
    db = MagicMock(name="db")
    mock_session.return_value.__enter__.return_value = db

    sources_q = MagicMock(name="sources_q")
    collections_q = MagicMock(name="collections_q")
    pathmaps_q = MagicMock(name="pathmaps_q")

    def query_side_effect(model_cls):
        name = getattr(model_cls, "__name__", "")
        if name == "Source":
            return sources_q
        if name == "Collection":
            return collections_q
        if name == "PathMapping":
            return pathmaps_q
        return MagicMock(name=f"{name}_query")

    db.query.side_effect = query_side_effect
    return db, sources_q, collections_q, pathmaps_q


def _mock_db_context(mock_get_db_context):
    db = MagicMock(name="db")
    cm = MagicMock(name="db_cm")
    cm.__enter__.return_value = db
    mock_get_db_context.return_value = cm

    sources_q = MagicMock(name="sources_q")
    collections_q = MagicMock(name="collections_q")
    pathmaps_q = MagicMock(name="pathmaps_q")

    def query_side_effect(model_cls):
        name = getattr(model_cls, "__name__", "")
        if name == "Source":
            return sources_q
        if name == "Collection":
            return collections_q
        if name == "PathMapping":
            return pathmaps_q
        return MagicMock(name=f"{name}_query")

    db.query.side_effect = query_side_effect
    return db, sources_q, collections_q, pathmaps_q


def test_collection_list_contract__help_flag(cli_runner):
    """B-0: The command exposes help with exit code 0."""

    result = cli_runner.invoke(app, ["collection", "list", "--help"])

    assert result.exit_code == 0
    assert "Show Collections for a Source" in result.stdout


def test_collection_list_contract__b1_lists_all_collections(cli_runner):
    with patch("retrovue.cli.commands.collection._get_db_context") as mock_get_db_context:
        _, _, collections_q, pathmaps_q = _mock_db_context(mock_get_db_context)

        collections_q.all.return_value = [
            _make_collection("4b2b05e7-d7d2-414a-a587-3f5df9b53f44", name="TV Shows"),
            _make_collection(
                "8c3d16f8-e8e3-525b-b698-4a6ef0c64e55",
                name="Movies",
                external_id="plex-2",
            ),
        ]
        pathmaps_q.filter.return_value.all.return_value = []

        result = cli_runner.invoke(app, ["collection", "list", "--json"])

        assert result.exit_code == 0

        data = json.loads(result.stdout)
        assert isinstance(data, list)
        assert {item["display_name"] for item in data} == {"TV Shows", "Movies"}


def test_collection_list_contract__b2_resolves_source_by_uuid(cli_runner):
    with patch("retrovue.cli.commands.collection._get_db_context") as mock_get_db_context:
        _, sources_q, collections_q, pathmaps_q = _mock_db_context(mock_get_db_context)

        resolved_source = SimpleNamespace(
            id=uuid.UUID("4b2b05e7-d7d2-414a-a587-3f5df9b53f44"),
            name="My Plex Server",
        )

        uuid_filter = MagicMock()
        uuid_filter.first.return_value = resolved_source
        sources_q.filter.side_effect = [uuid_filter]

        collections_q.filter.return_value.all.return_value = [
            _make_collection(
                "8c3d16f8-e8e3-525b-b698-4a6ef0c64e55",
                source_id=resolved_source.id,
                name="TV Shows",
            )
        ]
        pathmaps_q.filter.return_value.all.return_value = []

        result = cli_runner.invoke(
            app,
            ["collection", "list", "--source", str(resolved_source.id), "--json"],
        )

        assert result.exit_code == 0
        payload = json.loads(result.stdout)
        assert {item["display_name"] for item in payload} == {"TV Shows"}


def test_collection_list_contract__b2_resolves_source_by_external_id(cli_runner):
    with patch("retrovue.cli.commands.collection._get_db_context") as mock_get_db_context:
        _, sources_q, collections_q, pathmaps_q = _mock_db_context(mock_get_db_context)

        resolved_source = SimpleNamespace(
            id=uuid.UUID("4b2b05e7-d7d2-414a-a587-3f5df9b53f44"),
            name="My Plex Server",
            external_id="plex-5063d926",
        )

        uuid_filter = MagicMock()
        uuid_filter.first.return_value = None
        external_filter = MagicMock()
        external_filter.first.return_value = resolved_source
        name_filter = MagicMock()
        name_filter.all.return_value = []
        sources_q.filter.side_effect = [uuid_filter, external_filter, name_filter]

        collections_q.filter.return_value.all.return_value = [
            _make_collection(
                "8c3d16f8-e8e3-525b-b698-4a6ef0c64e55",
                source_id=resolved_source.id,
                name="TV Shows",
            )
        ]
        pathmaps_q.filter.return_value.all.return_value = []

        result = cli_runner.invoke(
            app,
            ["collection", "list", "--source", resolved_source.external_id, "--json"],
        )

        assert result.exit_code == 0
        payload = json.loads(result.stdout)
        assert {item["display_name"] for item in payload} == {"TV Shows"}


def test_collection_list_contract__b2_resolves_source_by_name(cli_runner):
    with patch("retrovue.cli.commands.collection._get_db_context") as mock_get_db_context:
        _, sources_q, collections_q, pathmaps_q = _mock_db_context(mock_get_db_context)

        resolved_source = SimpleNamespace(
            id=uuid.UUID("4b2b05e7-d7d2-414a-a587-3f5df9b53f44"),
            name="My Plex Server",
        )

        uuid_filter = MagicMock()
        uuid_filter.first.return_value = None
        external_filter = MagicMock()
        external_filter.first.return_value = None
        name_filter = MagicMock()
        name_filter.all.return_value = [resolved_source]
        sources_q.filter.side_effect = [uuid_filter, external_filter, name_filter]

        collections_q.filter.return_value.all.return_value = [
            _make_collection(
                "8c3d16f8-e8e3-525b-b698-4a6ef0c64e55",
                source_id=resolved_source.id,
                name="TV Shows",
            )
        ]
        pathmaps_q.filter.return_value.all.return_value = []

        result = cli_runner.invoke(
            app,
            ["collection", "list", "--source", "my plex server", "--json"],
        )

        assert result.exit_code == 0
        payload = json.loads(result.stdout)
        assert {item["display_name"] for item in payload} == {"TV Shows"}


def test_collection_list_contract__b3_errors_when_source_missing(cli_runner):
    with patch("retrovue.cli.commands.collection._get_db_context") as mock_get_db_context:
        _, sources_q, _, _ = _mock_db_context(mock_get_db_context)

        filter_mock = MagicMock()
        filter_mock.first.return_value = None
        filter_mock.all.return_value = []
        sources_q.filter.return_value = filter_mock

        result = cli_runner.invoke(app, ["collection", "list", "--source", "missing-source"])

        assert result.exit_code == 1
        out = result.stderr or result.stdout
        assert "Source 'missing-source' not found" in out


def test_collection_list_contract__b4_errors_when_source_ambiguous(cli_runner):
    with patch("retrovue.cli.commands.collection._get_db_context") as mock_get_db_context:
        _, sources_q, _, _ = _mock_db_context(mock_get_db_context)

        filter_mock = MagicMock()
        filter_mock.first.return_value = None
        filter_mock.all.return_value = [
            SimpleNamespace(id="id-1", name="My Server"),
            SimpleNamespace(id="id-2", name="My Server"),
        ]
        sources_q.filter.return_value = filter_mock

        result = cli_runner.invoke(app, ["collection", "list", "--source", "My Server"])

        assert result.exit_code == 1
        out = result.stderr or result.stdout
        assert "Multiple sources" in out


def test_collection_list_contract__b5_filters_collections_by_source(cli_runner):
    with patch("retrovue.cli.commands.collection._get_db_context") as mock_get_db_context:
        _, sources_q, collections_q, pathmaps_q = _mock_db_context(mock_get_db_context)

        resolved_source = SimpleNamespace(
            id=uuid.UUID("4b2b05e7-d7d2-414a-a587-3f5df9b53f44"),
            name="My Plex Server",
        )

        sources_q.filter.return_value.first.return_value = resolved_source

        collections_q.filter.return_value.all.return_value = [
            _make_collection(
                "8c3d16f8-e8e3-525b-b698-4a6ef0c64e55",
                source_id=resolved_source.id,
                name="TV Shows",
            )
        ]
        pathmaps_q.filter.return_value.all.return_value = []

        result = cli_runner.invoke(app, ["collection", "list", "--source", resolved_source.name, "--json"])

        assert result.exit_code == 0
        data = json.loads(result.stdout)
        assert {item["display_name"] for item in data} == {"TV Shows"}


def test_collection_list_contract__b6_returns_structured_json(cli_runner):
    with patch("retrovue.cli.commands.collection._get_db_context") as mock_get_db_context:
        _, _, collections_q, pathmaps_q = _mock_db_context(mock_get_db_context)

        collections_q.all.return_value = [
            _make_collection("4b2b05e7-d7d2-414a-a587-3f5df9b53f44"),
        ]
        pathmaps_q.filter.return_value.all.return_value = [
            _make_path_mapping(local_path="/local/tv"),
        ]

        result = cli_runner.invoke(app, ["collection", "list", "--json"])

        assert result.exit_code == 0

        payload = json.loads(result.stdout)
        assert isinstance(payload, list)
        assert len(payload) == 1
        assert_contains_fields(
            payload[0],
            {
                "collection_id": "4b2b05e7-d7d2-414a-a587-3f5df9b53f44",
                "external_id": "plex-1",
                "display_name": "TV Shows",
                "sync_enabled": True,
                "ingestable": True,
                "mapping_pairs": ...,
            },
        )


def test_collection_list_contract__b7_output_is_deterministic(cli_runner):
    with patch("retrovue.cli.commands.collection._get_db_context") as mock_get_db_context:
        _, _, collections_q, pathmaps_q = _mock_db_context(mock_get_db_context)

        collections_q.all.return_value = [
            _make_collection("4b2b05e7-d7d2-414a-a587-3f5df9b53f44", name="TV Shows"),
            _make_collection(
                "8c3d16f8-e8e3-525b-b698-4a6ef0c64e55",
                name="Movies",
                external_id="plex-2",
            ),
        ]
        pathmaps_q.filter.return_value.all.return_value = []

        first = cli_runner.invoke(app, ["collection", "list", "--json"])
        second = cli_runner.invoke(app, ["collection", "list", "--json"])

        assert first.exit_code == 0
        assert second.exit_code == 0
        assert json.loads(first.stdout) == json.loads(second.stdout)


def test_collection_list_contract__b8_reports_no_collections(cli_runner):
    with patch("retrovue.cli.commands.collection._get_db_context") as mock_get_db_context:
        _, _, collections_q, _ = _mock_db_context(mock_get_db_context)

        collections_q.all.return_value = []

        json_result = cli_runner.invoke(app, ["collection", "list", "--json"])
        human_result = cli_runner.invoke(app, ["collection", "list"])

        assert json_result.exit_code == 0
        assert human_result.exit_code == 0
        assert "No collections found" in human_result.stdout


def test_collection_list_contract__b9_is_read_only(cli_runner):
    with patch("retrovue.cli.commands.collection._get_db_context") as mock_get_db_context:
        db, _, collections_q, pathmaps_q = _mock_db_context(mock_get_db_context)

        collections_q.all.return_value = [
            _make_collection("4b2b05e7-d7d2-414a-a587-3f5df9b53f44"),
        ]
        pathmaps_q.filter.return_value.all.return_value = []

        result = cli_runner.invoke(app, ["collection", "list", "--json"])

        assert result.exit_code == 0
        db.commit.assert_not_called()
        db.add.assert_not_called()


def test_collection_list_contract__b10_b11_test_db_uses_isolated_session(cli_runner):
    with patch("retrovue.cli.commands.collection.get_sessionmaker") as mock_get_sm, patch(
        "retrovue.cli.commands.collection.session"
    ) as mock_default_session:
        test_sessionmaker = MagicMock(name="TestSessionmaker")
        test_context = MagicMock(name="TestSessionContext")
        test_sessionmaker.return_value = test_context
        mock_get_sm.return_value = test_sessionmaker

        db = MagicMock(name="test_db")
        test_context.__enter__.return_value = db

        sources_q = MagicMock()
        collections_q = MagicMock()
        pathmaps_q = MagicMock()

        def query_side_effect(model_cls):
            name = getattr(model_cls, "__name__", "")
            if name == "Source":
                return sources_q
            if name == "Collection":
                return collections_q
            if name == "PathMapping":
                return pathmaps_q
            return MagicMock()

        db.query.side_effect = query_side_effect

        resolved_source = SimpleNamespace(
            id=uuid.UUID("4b2b05e7-d7d2-414a-a587-3f5df9b53f44"),
            name="My Plex Server",
        )
        sources_q.filter.return_value.first.return_value = resolved_source
        collections_q.filter.return_value.all.return_value = [
            _make_collection(
                "8c3d16f8-e8e3-525b-b698-4a6ef0c64e55",
                source_id=resolved_source.id,
                name="Movies",
            )
        ]
        pathmaps_q.filter.return_value.all.return_value = []

        result = cli_runner.invoke(
            app,
            ["collection", "list", "--source", resolved_source.name, "--json", "--test-db"],
        )

        assert result.exit_code == 0
        mock_get_sm.assert_called_once_with(for_test=True)
        mock_default_session.assert_not_called()
        payload = json.loads(result.stdout)
        assert {item["display_name"] for item in payload} == {"Movies"}


def test_collection_list_contract__b12_skips_external_systems(cli_runner):
    with patch("retrovue.cli.commands.collection._get_db_context") as mock_get_db_context, patch(
        "retrovue.cli.commands.collection.get_importer"
    ) as mock_get_importer:
        _, _, collections_q, pathmaps_q = _mock_db_context(mock_get_db_context)

        collections_q.all.return_value = [
            _make_collection("4b2b05e7-d7d2-414a-a587-3f5df9b53f44"),
        ]
        pathmaps_q.filter.return_value.all.return_value = []

        result = cli_runner.invoke(app, ["collection", "list", "--json"])

        assert result.exit_code == 0
        mock_get_importer.assert_not_called()
