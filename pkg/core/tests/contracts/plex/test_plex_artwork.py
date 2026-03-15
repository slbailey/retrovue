"""
Contract tests for INV-PLEX-ARTWORK-001.

Contract: docs/contracts/plex/INV-PLEX-ARTWORK-001.md

Invariant:
    Every Plex-sourced asset MUST have its artwork URL persisted in
    asset_editorial.payload at ingest time. The XMLTV serving path
    MUST read artwork URLs from persisted editorial metadata — it
    MUST NOT make live upstream API calls to resolve artwork.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch
from xml.etree.ElementTree import fromstring


# ===========================================================================
# Test 1: Importer persists thumb_url in editorial payload
# ===========================================================================

class TestPlexArtworkIngest:
    """Plex importer MUST store thumb_url in editorial payload."""

    def test_thumb_url_persisted_in_editorial(self):
        """When Plex metadata includes thumbUrl, editorial payload MUST contain thumb_url."""
        from retrovue.adapters.importers.plex_importer import PlexImporter

        # Minimal Plex library and item structures.
        library = {"key": "1", "title": "Movies", "type": "movie"}
        item = {
            "ratingKey": "12345",
            "title": "Test Movie",
            "type": "movie",
            "year": "2024",
        }

        # Mock PlexClient to return metadata with thumbUrl.
        detailed_meta = {
            "title": "Test Movie",
            "summary": "A test movie.",
            "year": "2024",
            "duration": 5400000,
            "thumbUrl": "https://plex.example.com/library/metadata/12345/thumb/1700000000?X-Plex-Token=test-token",
            "Media": [],
        }
        mock_client = MagicMock()
        mock_client.base_url = "https://plex.example.com"
        mock_client.token = "test-token"
        mock_client.get_metadata.return_value = detailed_meta
        mock_client.get_episode_metadata.return_value = detailed_meta

        importer = PlexImporter.__new__(PlexImporter)
        importer.client = mock_client

        discovered = importer._create_discovered_item(item, library)

        assert discovered is not None, (
            "INV-PLEX-ARTWORK-001: _build_discovered_item must return a DiscoveredItem"
        )
        editorial = discovered.editorial
        assert "thumb_url" in editorial, (
            "INV-PLEX-ARTWORK-001 VIOLATION: thumb_url not persisted in editorial payload. "
            "Artwork URL must be captured at ingest time, not resolved at serve time."
        )
        assert "plex.example.com" in editorial["thumb_url"], (
            f"INV-PLEX-ARTWORK-001: thumb_url must contain the Plex server URL, "
            f"got: {editorial['thumb_url']}"
        )

    def test_no_thumb_url_when_plex_has_none(self):
        """When Plex metadata has no thumb, editorial MUST NOT contain thumb_url."""
        from retrovue.adapters.importers.plex_importer import PlexImporter

        library = {"key": "1", "title": "Movies", "type": "movie"}
        item = {
            "ratingKey": "12345",
            "title": "No Art Movie",
            "type": "movie",
            "year": "2024",
        }

        detailed_meta = {
            "title": "No Art Movie",
            "summary": "No artwork.",
            "year": "2024",
            "duration": 5400000,
            # No thumbUrl key.
            "Media": [],
        }
        mock_client = MagicMock()
        mock_client.base_url = "https://plex.example.com"
        mock_client.token = "test-token"
        mock_client.get_metadata.return_value = detailed_meta
        mock_client.get_episode_metadata.return_value = detailed_meta

        importer = PlexImporter.__new__(PlexImporter)
        importer.client = mock_client

        discovered = importer._create_discovered_item(item, library)
        assert discovered is not None
        # thumb_url should be absent (not None, not empty string).
        assert "thumb_url" not in discovered.editorial or discovered.editorial.get("thumb_url") is None

    def test_episode_uses_series_poster_not_screenshot(self):
        """For TV episodes, thumb_url MUST be the series poster (grandparentThumb),
        NOT the episode screenshot (thumb)."""
        from retrovue.adapters.importers.plex_importer import PlexImporter

        library = {"key": "2", "title": "RetroTV", "type": "show"}
        item = {
            "ratingKey": "7599",
            "title": "Midnight on the Firing Line",
            "type": "episode",
            "year": "1994",
            "show_title": "Babylon 5",
            "season_index": "1",
            "episode_index": "1",
        }

        series_poster = "https://plex.example.com/library/metadata/100/thumb/170000?X-Plex-Token=tok"
        episode_screenshot = "https://plex.example.com/library/metadata/7599/thumb/170000?X-Plex-Token=tok"

        detailed_meta = {
            "title": "Midnight on the Firing Line",
            "grandparentTitle": "Babylon 5",
            "parentIndex": "1",
            "index": "1",
            "summary": "First episode.",
            "year": "1994",
            "duration": 2640000,
            "thumbUrl": episode_screenshot,
            "grandparentThumbUrl": series_poster,
            "Media": [],
        }
        mock_client = MagicMock()
        mock_client.base_url = "https://plex.example.com"
        mock_client.token = "tok"
        mock_client.get_metadata.return_value = detailed_meta
        mock_client.get_episode_metadata.return_value = detailed_meta

        importer = PlexImporter.__new__(PlexImporter)
        importer.client = mock_client

        discovered = importer._create_discovered_item(item, library)
        assert discovered is not None
        editorial = discovered.editorial
        assert "thumb_url" in editorial, (
            "INV-PLEX-ARTWORK-001: TV episode must have thumb_url"
        )
        assert editorial["thumb_url"] == series_poster, (
            f"INV-PLEX-ARTWORK-001 VIOLATION: TV episode thumb_url must be the series poster, "
            f"not the episode screenshot. Got: {editorial['thumb_url']}"
        )


# ===========================================================================
# Test 2: Artwork resolver reads from editorial, no live API
# ===========================================================================

class TestPlexArtworkResolve:
    """Artwork resolver MUST read from editorial payload, MUST NOT call Plex API."""

    def test_resolve_from_editorial_no_api_call(self):
        """resolve_programme_poster_url MUST return thumb_url from editorial
        without making any PlexClient calls."""
        import uuid
        from retrovue.web.artwork import resolve_programme_poster_url

        asset_uuid = uuid.uuid4()
        thumb = "https://plex.example.com/library/metadata/12345/thumb/1700000000?X-Plex-Token=tok"

        # Mock DB session that returns an asset with editorial containing thumb_url.
        mock_asset = MagicMock()
        mock_asset.uuid = asset_uuid
        mock_asset.uri = "plex://12345"
        mock_asset.collection_uuid = uuid.uuid4()

        mock_editorial = MagicMock()
        mock_editorial.payload = {"thumb_url": thumb}

        mock_db = MagicMock()

        # Set up query chain: Asset query returns mock_asset,
        # AssetEditorial query returns mock_editorial.
        def fake_query(model):
            q = MagicMock()
            from retrovue.domain.entities import Asset, AssetEditorial
            if model is Asset:
                q.filter.return_value.first.return_value = mock_asset
            elif model is AssetEditorial:
                q.filter.return_value.first.return_value = mock_editorial
            else:
                q.filter.return_value.first.return_value = None
            return q

        mock_db.query = fake_query

        # Patch PlexClient to detect if it's called.
        with patch("retrovue.adapters.importers.plex_importer.PlexClient", side_effect=AssertionError(
            "INV-PLEX-ARTWORK-001 VIOLATION: PlexClient instantiated during artwork resolve"
        )):
            url = resolve_programme_poster_url(asset_uuid, mock_db)

        assert url == thumb, (
            f"INV-PLEX-ARTWORK-001: Expected thumb_url from editorial, got: {url}"
        )

    def test_missing_thumb_url_returns_none(self):
        """When editorial has no thumb_url, resolver MUST return None (placeholder),
        MUST NOT fall back to live Plex API."""
        import uuid
        from retrovue.web.artwork import resolve_programme_poster_url

        asset_uuid = uuid.uuid4()

        mock_asset = MagicMock()
        mock_asset.uuid = asset_uuid
        mock_asset.uri = "plex://12345"
        mock_asset.collection_uuid = uuid.uuid4()

        mock_editorial = MagicMock()
        mock_editorial.payload = {"title": "Some Movie"}  # No thumb_url.

        mock_db = MagicMock()

        def fake_query(model):
            q = MagicMock()
            from retrovue.domain.entities import Asset, AssetEditorial
            if model is Asset:
                q.filter.return_value.first.return_value = mock_asset
            elif model is AssetEditorial:
                q.filter.return_value.first.return_value = mock_editorial
            else:
                q.filter.return_value.first.return_value = None
            return q

        mock_db.query = fake_query

        with patch("retrovue.adapters.importers.plex_importer.PlexClient", side_effect=AssertionError(
            "INV-PLEX-ARTWORK-001 VIOLATION: PlexClient must not be called as fallback"
        )):
            url = resolve_programme_poster_url(asset_uuid, mock_db)

        assert url is None, (
            f"INV-PLEX-ARTWORK-001: Expected None for missing thumb_url, got: {url}"
        )


# ===========================================================================
# Test 3: XMLTV icon uses persisted artwork URL
# ===========================================================================

class TestPlexArtworkXmltv:
    """XMLTV <icon> elements MUST use URLs that resolve without live API calls."""

    def test_xmltv_icon_uses_persisted_thumb_url(self):
        """generate_xmltv MUST produce <icon> elements with base_url + asset_id path
        that the artwork endpoint resolves from editorial payload."""
        from retrovue.web.iptv import generate_xmltv

        channels = [{"channel_id": "test-ch", "name": "Test", "channel_id_int": 1}]
        entries = [{
            "channel_id": "test-ch",
            "start_time": "2026-03-14T10:00:00+00:00",
            "end_time": "2026-03-14T11:00:00+00:00",
            "title": "Test Movie",
            "asset_id": "2d7f93ac-c273-43d0-9663-cef6292da380",
        }]

        xml_str = generate_xmltv(channels, entries, base_url="http://retrovue:8000")
        root = fromstring(xml_str)

        progs = root.findall("programme")
        assert len(progs) == 1

        icon = progs[0].find("icon")
        assert icon is not None, (
            "INV-PLEX-ARTWORK-001: XMLTV programme MUST have <icon> element when asset_id is present"
        )
        src = icon.get("src")
        assert "art/program/2d7f93ac-c273-43d0-9663-cef6292da380.jpg" in src, (
            f"INV-PLEX-ARTWORK-001: icon src must reference artwork endpoint, got: {src}"
        )
