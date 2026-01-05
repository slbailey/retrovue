"""
Plex Media Server importer plugin for RetroVue.

This importer connects to Plex Media Server instances and discovers content
from their libraries, following the plugin contract defined in docs/developer/PluginAuthoring.md.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING, Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .base import (
    BaseImporter,
    DiscoveredItem,
    ImporterConfig,
    ImporterConfigurationError,
    ImporterConnectionError,
    ImporterError,
    UpdateFieldSpec,
)

if TYPE_CHECKING:
    from ...domain.entities import Collection

logger = logging.getLogger(__name__)


class PlexClient:
    """Plex HTTP client for fetching libraries and items."""

    def __init__(self, base_url: str, token: str, library_key: str | None = None):
        """
        Initialize Plex client.

        Args:
            base_url: Plex server base URL (e.g., "http://127.0.0.1:32400")
            token: Plex authentication token
        """
        # Be resilient to accidental whitespace/newlines
        self.base_url = base_url.strip().rstrip("/")
        self.token = token.strip()
        self.session = self._create_session()

    def _create_session(self) -> requests.Session:
        """Create a requests session with retry logic and Plex headers."""
        import os
        import uuid as _uuid

        session = requests.Session()

        # Configure retry strategy
        retry_strategy = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
        )

        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("http://", adapter)
        session.mount("https://", adapter)

        # Standard Plex headers improve compatibility behind proxies/CDNs
        client_id = str(_uuid.uuid4())
        session.headers.update(
            {
                "X-Plex-Product": "Retrovue",
                "X-Plex-Version": "1.0",
                "X-Plex-Client-Identifier": client_id,
                "X-Plex-Platform": "Python",
                "Accept": "application/xml",
            }
        )

        # Allow disabling SSL verification for self-signed certs when explicitly requested
        if os.getenv("RETROVUE_INSECURE_SSL") == "1":
            session.verify = False

        return session

    def get_libraries(self) -> list[dict[str, Any]]:
        """
        Get all libraries from the Plex server.

        Returns:
            List of library information dictionaries

        Raises:
            ImporterError: If the request fails
        """
        try:
            url = f"{self.base_url}/library/sections"
            # Send token both as header and query param for maximum compatibility
            params = {"X-Plex-Token": self.token}
            headers = {"X-Plex-Token": self.token}
            response = self.session.get(url, params=params, headers=headers, timeout=20)
            response.raise_for_status()

            # Parse XML response
            import xml.etree.ElementTree as ET

            root = ET.fromstring(response.content)

            libraries = []
            sections = root.findall("Directory")

            for section in sections:
                lib_id = section.get("key")
                lib_name = section.get("title")
                lib_type = section.get("type")

                if lib_id and lib_name:
                    # Extract filesystem locations from Location elements
                    locations = []
                    for location in section.findall("Location"):
                        path = location.get("path")
                        if path:
                            locations.append(path)

                    libraries.append(
                        {"key": lib_id, "title": lib_name, "type": lib_type, "locations": locations}
                    )

            return libraries

        except requests.RequestException as e:
            raise ImporterError(f"Failed to fetch libraries: {e}") from e

    def get_library_items(
        self,
        library_key: str,
        title_filter: str | None = None,
        season_filter: int | None = None,
        episode_filter: int | None = None,
    ) -> list[dict[str, Any]]:
        """
        Get all items from a specific library.

        Args:
            library_key: The library key to fetch items from

        Returns:
            List of item information dictionaries

        Raises:
            ImporterError: If the request fails
        """
        try:
            # Get library content to determine type
            url = f"{self.base_url}/library/sections/{library_key}/all"
            params = {"X-Plex-Token": self.token}
            headers = {"X-Plex-Token": self.token}
            response = self.session.get(url, params=params, headers=headers, timeout=20)
            response.raise_for_status()

            import xml.etree.ElementTree as ET

            root = ET.fromstring(response.content)
            library_type = root.get("type", "")
            view_group = root.get("viewGroup", "")

            items = []

            # If it's a TV show library, drill down to get episodes
            if library_type == "show" or view_group == "show":
                # Use the shows we already have from the root
                shows = root.findall("Directory")

                # For each show, get its seasons and episodes
                for show in shows:
                    show_key = show.get("ratingKey")
                    show_title = show.get("title")

                    # Apply title filter if specified
                    if (
                        title_filter is not None
                        and show_title is not None
                        and title_filter.lower() not in show_title.lower()
                    ):
                        continue

                    # Get seasons for this show
                    seasons_url = f"{self.base_url}/library/metadata/{show_key}/children"
                    seasons_response = self.session.get(
                        seasons_url, params=params, headers={"X-Plex-Token": self.token}, timeout=20
                    )
                    seasons_response.raise_for_status()

                    seasons_root = ET.fromstring(seasons_response.content)
                    seasons = seasons_root.findall("Directory")

                    # For each season, get its episodes
                    for season in seasons:
                        season_key = season.get("ratingKey")
                        season_title = season.get("title")
                        season_index = season.get("index")

                        # Skip seasons without valid rating key
                        if not season_key:
                            continue

                        # Apply season filter if specified
                        if (
                            season_filter is not None
                            and season_index is not None
                            and int(season_index) != season_filter
                        ):
                            continue

                        # Get episodes for this season
                        episodes_url = f"{self.base_url}/library/metadata/{season_key}/children"
                        episodes_response = self.session.get(
                            episodes_url,
                            params=params,
                            headers={"X-Plex-Token": self.token},
                            timeout=20,
                        )
                        episodes_response.raise_for_status()

                        episodes_root = ET.fromstring(episodes_response.content)
                        episodes = episodes_root.findall("Video")

                        # Process each episode
                        for episode in episodes:
                            rating_key = episode.get("ratingKey")
                            title = episode.get("title")
                            year = episode.get("year")
                            type_attr = episode.get("type")
                            episode_index = episode.get("index")

                            # Apply episode filter if specified
                            if (
                                episode_filter is not None
                                and episode_index is not None
                                and int(episode_index) != episode_filter
                            ):
                                continue

                            # Get file information
                            media = episode.find("Media")
                            file_path = None
                            file_size = None
                            duration = None

                            if media is not None:
                                part = media.find("Part")
                                if part is not None:
                                    file_path = part.get("file")
                                    file_size = part.get("size")
                                duration = media.get("duration")

                            if rating_key and title and file_path:
                                items.append(
                                    {
                                        "ratingKey": rating_key,
                                        "title": title,
                                        "year": year,
                                        "type": type_attr,
                                        "file_path": file_path,
                                        "fileSize": file_size,
                                        "duration": duration,
                                        "updatedAt": episode.get("updatedAt"),
                                        "show_title": show_title,
                                        "season_title": season_title,
                                        "season_index": season_index,
                                        "episode_index": episode.get("index"),
                                    }
                                )
            else:
                # For movie libraries, get movies directly
                url = f"{self.base_url}/library/sections/{library_key}/all"
                response = self.session.get(
                    url, params=params, headers={"X-Plex-Token": self.token}, timeout=20
                )
                response.raise_for_status()

                root = ET.fromstring(response.content)

                # Handle Video elements (movies)
                for video in root.findall("Video"):
                    rating_key = video.get("ratingKey")
                    title = video.get("title")
                    year = video.get("year")
                    type_attr = video.get("type")

                    # Get file information
                    media = video.find("Media")
                    file_path = None
                    file_size = None
                    duration = None

                    if media is not None:
                        part = media.find("Part")
                        if part is not None:
                            file_path = part.get("file")
                            file_size = part.get("size")
                        duration = media.get("duration")

                    if rating_key and title and file_path:
                        items.append(
                            {
                                "ratingKey": rating_key,
                                "title": title,
                                "year": year,
                                "type": type_attr,
                                "file_path": file_path,
                                "fileSize": file_size,
                                "duration": duration,
                                "updatedAt": video.get("updatedAt"),
                            }
                        )

            return items

        except requests.RequestException as e:
            raise ImporterError(f"Failed to fetch library items: {e}") from e

    def get_metadata(self, rating_key: int) -> dict[str, Any]:
        """
        Get detailed metadata for a specific item (episode or movie) by rating key.

        Args:
            rating_key: The Plex rating key for the item

        Returns:
            Dictionary containing item metadata

        Raises:
            ImporterError: If the request fails
        """
        try:
            url = f"{self.base_url}/library/metadata/{rating_key}"
            params: dict[str, str | int] = {
                "X-Plex-Token": self.token,
                "includeGuids": 1,
                "includeMarkers": 1,
                "includePreferences": 1,
                "includeConcerts": 1,
                "includeChapters": 1,
                "includeFields": "summary,genre,contentRating,Media",
            }
            # Reuse session headers; do not override here
            response = self.session.get(url, params=params, timeout=20)
            response.raise_for_status()

            # Debug output removed

            # Parse XML response
            import xml.etree.ElementTree as ET

            root = ET.fromstring(response.content)

            # Find the Video element (support nested structures)
            video = root.find(".//Video")
            if video is None:
                logger.warning(
                    "Plex metadata for ratingKey=%s had no <Video> element",
                    rating_key,
                )
                return {}

            # Extract metadata
            metadata: dict[str, Any] = {
                "ratingKey": video.get("ratingKey"),
                "title": video.get("title"),
                "originalTitle": video.get("originalTitle"),
                "grandparentTitle": video.get("grandparentTitle"),
                "parentIndex": video.get("parentIndex"),
                "index": video.get("index"),
                "summary": video.get("summary"),
                "year": video.get("year"),
                "contentRating": video.get("contentRating"),
                "originallyAvailableAt": video.get("originallyAvailableAt"),
                "studio": video.get("studio"),
                "duration": video.get("duration"),
                "Media": [],
                "genres": [],
            }

            # Provide simplified keys in addition to raw attribute names
            if metadata.get("contentRating"):
                metadata["content_rating"] = metadata["contentRating"]
            if metadata.get("originalTitle"):
                metadata["original_title"] = metadata["originalTitle"]
            if metadata.get("originallyAvailableAt"):
                metadata["release_date"] = metadata["originallyAvailableAt"]

            # Extract Media information
            for media in video.findall("Media"):
                media_info: dict[str, Any] = {
                    "duration": media.get("duration"),
                    "videoCodec": media.get("videoCodec"),
                    "audioCodec": media.get("audioCodec"),
                    "container": media.get("container"),
                    "Part": [],
                }

                # Extract Part information
                for part in media.findall("Part"):
                    part_info = {
                        "file": part.get("file"),
                        "size": part.get("size"),
                        "duration": part.get("duration"),
                    }
                    media_info["Part"].append(part_info)

                metadata["Media"].append(media_info)

            # Extract Genre tags
            try:
                genres = []
                for genre in video.findall("Genre"):
                    tag = genre.get("tag")
                    if tag:
                        genres.append(tag)
                metadata["genres"] = genres
            except Exception:
                pass

            # Additional tag arrays
            def _extract_tags(tag_name: str) -> list[str]:
                tags: list[str] = []
                try:
                    for el in video.findall(tag_name):
                        t = el.get("tag")
                        if t:
                            tags.append(t)
                except Exception:
                    pass
                return tags

            metadata["country_tags"] = _extract_tags("Country")
            metadata["collection_tags"] = _extract_tags("Collection")
            metadata["director_tags"] = _extract_tags("Director")
            metadata["writer_tags"] = _extract_tags("Writer")
            metadata["cast_tags"] = _extract_tags("Role")

            # Warn if detailed fields are missing
            if not (metadata.get("summary") or metadata.get("contentRating") or (metadata.get("genres") or [])):
                logger.warning(
                    "Plex metadata had no summary/genres/contentRating",
                    extra={"rating_key": rating_key},
                )

            return metadata

        except requests.RequestException as e:
            raise ImporterError(f"Failed to fetch episode metadata: {e}") from e

    # Backward compatibility shim
    def get_episode_metadata(self, rating_key: int) -> dict[str, Any]:
        return self.get_metadata(rating_key)

    def find_episode_by_sse(self, series_title: str, season: int, episode: int) -> dict[str, Any]:
        """
        Find an episode by series title, season, and episode number.

        Args:
            series_title: The series title
            season: Season number
            episode: Episode number

        Returns:
            Episode metadata

        Raises:
            ImporterError: If episode not found or multiple matches
        """
        try:
            # Step 1: Find the series
            series_list = self.find_series_by_title(series_title)

            if not series_list:
                raise ImporterError(f"No series found matching '{series_title}'")

            # Try to find the best match if multiple results
            if len(series_list) > 1:
                # Look for exact title match first
                exact_matches = [
                    s for s in series_list if s["title"].lower() == series_title.lower()
                ]
                if exact_matches:
                    series = exact_matches[0]
                else:
                    # Look for partial matches
                    partial_matches = [
                        s for s in series_list if series_title.lower() in s["title"].lower()
                    ]
                    if partial_matches:
                        series = partial_matches[0]
                    else:
                        titles = [s["title"] for s in series_list]
                        raise ImporterError(
                            f"Multiple series found matching '{series_title}': {titles}. Please be more specific."
                        )
            else:
                series = series_list[0]

            series_rating_key = int(series["ratingKey"])

            # Step 2: Get seasons for the series
            seasons = self.get_series_seasons(series_rating_key)

            # Find the requested season
            matching_seasons = [s for s in seasons if int(s.get("parentIndex", 0)) == season]

            if not matching_seasons:
                available_seasons = [int(s.get("parentIndex", 0)) for s in seasons]
                raise ImporterError(
                    f"Season {season} not found for series '{series_title}'. Available seasons: {available_seasons}"
                )

            if len(matching_seasons) > 1:
                # If multiple seasons with same number, prefer the one that's not a special/collection
                main_season = None
                for s in matching_seasons:
                    title = s.get("title", "").lower()
                    # Prefer seasons that don't have "special", "collection", "complete" in the title
                    if not any(
                        word in title for word in ["special", "collection", "complete", "box set"]
                    ):
                        main_season = s
                        break

                if main_season:
                    matching_seasons = [main_season]
                else:
                    # If no clear main season, use the first one
                    matching_seasons = [matching_seasons[0]]

            season_data = matching_seasons[0]
            season_rating_key = int(season_data["ratingKey"])

            # Step 3: Get episodes for the season
            episodes = self.get_season_episodes(season_rating_key)

            # Find the requested episode
            matching_episodes = [e for e in episodes if int(e.get("index", 0)) == episode]

            if not matching_episodes:
                available_episodes = [int(e.get("index", 0)) for e in episodes]
                raise ImporterError(
                    f"Episode {episode} not found in season {season} of '{series_title}'. Available episodes: {available_episodes}"
                )

            if len(matching_episodes) > 1:
                raise ImporterError(
                    f"Multiple episodes found with number {episode} in season {season} of '{series_title}'"
                )

            episode_data = matching_episodes[0]
            return episode_data

        except requests.RequestException as e:
            raise ImporterError(f"Failed to find episode: {e}") from e

    def find_series_by_title(self, series_title: str) -> list[dict[str, Any]]:
        """
        Find series by title (case-insensitive search).

        Args:
            series_title: The series title to search for

        Returns:
            List of matching series

        Raises:
            ImporterError: If the request fails
        """
        try:
            # First try the global search without type restriction
            url = f"{self.base_url}/search"
            params = {"X-Plex-Token": self.token, "query": series_title}
            response = self.session.get(
                url, params=params, headers={"X-Plex-Token": self.token}, timeout=20
            )
            response.raise_for_status()

            # Parse XML response
            import xml.etree.ElementTree as ET

            root = ET.fromstring(response.content)

            series_list = []
            for video in root.findall("Video"):
                if video.get("type") == "show":
                    series_info = {
                        "ratingKey": video.get("ratingKey"),
                        "title": video.get("title"),
                        "year": video.get("year"),
                        "summary": video.get("summary"),
                    }
                    series_list.append(series_info)

            # If no results from global search, try searching in TV libraries
            if not series_list:
                series_list = self._search_in_tv_libraries(series_title)

            return series_list

        except requests.RequestException as e:
            raise ImporterError(f"Failed to search for series: {e}") from e

    def _search_in_tv_libraries(self, series_title: str) -> list[dict[str, Any]]:
        """
        Search for series in TV libraries if global search fails.

        Args:
            series_title: The series title to search for

        Returns:
            List of matching series
        """
        try:
            # Get all libraries first
            libraries = self.get_libraries()
            tv_libraries = [lib for lib in libraries if lib.get("type") == "show"]

            series_list = []
            for library in tv_libraries:
                try:
                    # Try browsing the library directly instead of searching
                    url = f"{self.base_url}/library/sections/{library['key']}/all"
                    params = {"X-Plex-Token": self.token}

                    response = self.session.get(
                        url, params=params, headers={"X-Plex-Token": self.token}, timeout=20
                    )
                    response.raise_for_status()

                    # Parse XML response
                    import xml.etree.ElementTree as ET

                    root = ET.fromstring(response.content)

                    for directory in root.findall("Directory"):
                        if directory.get("type") == "show":
                            title = directory.get("title", "")
                            # Check if this series matches our search (case-insensitive)
                            if series_title.lower() in title.lower():
                                series_info = {
                                    "ratingKey": directory.get("ratingKey"),
                                    "title": title,
                                    "year": directory.get("year"),
                                    "summary": directory.get("summary"),
                                    "library": library["title"],
                                }
                                series_list.append(series_info)

                except Exception:
                    continue
            return series_list

        except Exception:
            return []

    def get_series_seasons(self, series_rating_key: int) -> list[dict[str, Any]]:
        """
        Get seasons for a series.

        Args:
            series_rating_key: The series rating key

        Returns:
            List of seasons

        Raises:
            ImporterError: If the request fails
        """
        try:
            url = f"{self.base_url}/library/metadata/{series_rating_key}/children"
            params = {"X-Plex-Token": self.token}
            response = self.session.get(
                url, params=params, headers={"X-Plex-Token": self.token}, timeout=20
            )
            response.raise_for_status()

            # Parse XML response
            import xml.etree.ElementTree as ET

            root = ET.fromstring(response.content)

            seasons = []
            for directory in root.findall("Directory"):
                if directory.get("type") == "season":
                    seasons.append(
                        {
                            "ratingKey": directory.get("ratingKey"),
                            "title": directory.get("title"),
                            "parentIndex": directory.get("parentIndex"),
                            "index": directory.get("index"),
                        }
                    )

            return seasons

        except requests.RequestException as e:
            raise ImporterError(f"Failed to fetch series seasons: {e}") from e

    def get_season_episodes(self, season_rating_key: int) -> list[dict[str, Any]]:
        """
        Get episodes for a season.

        Args:
            season_rating_key: The season rating key

        Returns:
            List of episodes

        Raises:
            ImporterError: If the request fails
        """
        try:
            url = f"{self.base_url}/library/metadata/{season_rating_key}/children"
            params = {"X-Plex-Token": self.token}
            response = self.session.get(
                url, params=params, headers={"X-Plex-Token": self.token}, timeout=20
            )
            response.raise_for_status()

            # Parse XML response
            import xml.etree.ElementTree as ET

            root = ET.fromstring(response.content)

            episodes: list[dict[str, Any]] = []
            for video in root.findall("Video"):
                if video.get("type") == "episode":
                    episodes.append(
                        {
                            "ratingKey": video.get("ratingKey"),
                            "title": video.get("title"),
                            "grandparentTitle": video.get("grandparentTitle"),
                            "parentIndex": video.get("parentIndex"),
                            "index": video.get("index"),
                            "summary": video.get("summary"),
                            "year": video.get("year"),
                            "duration": video.get("duration"),
                            "Media": [],
                        }
                    )

                    # Extract Media information
                    for media in video.findall("Media"):
                        media_info: dict[str, Any] = {
                            "duration": media.get("duration"),
                            "videoCodec": media.get("videoCodec"),
                            "audioCodec": media.get("audioCodec"),
                            "container": media.get("container"),
                            "bitrate": media.get("bitrate"),
                            "Part": [],
                        }

                        # Extract Part information
                        for part in media.findall("Part"):
                            part_info = {
                                "file": part.get("file"),
                                "size": part.get("size"),
                                "duration": part.get("duration"),
                            }
                            media_info["Part"].append(part_info)

                        episodes[-1]["Media"].append(media_info)

            return episodes

        except requests.RequestException as e:
            raise ImporterError(f"Failed to fetch season episodes: {e}") from e


class PlexImporter(BaseImporter):
    """
    Plex importer plugin following the plugin contract.

    This importer connects to Plex servers and discovers content from their
    libraries, extracting metadata and file paths.
    """

    name = "plex"

    def __init__(self, base_url: str, token: str):
        """
        Initialize the Plex importer.

        Args:
            base_url: Plex server base URL
            token: Plex authentication token
        """
        # Normalize early so both BaseImporter and client get clean values
        cleaned_base_url = base_url.strip()
        cleaned_token = token.strip()
        super().__init__(base_url=cleaned_base_url, token=cleaned_token)
        self.base_url = cleaned_base_url
        self.token = cleaned_token
        self.client = PlexClient(cleaned_base_url, cleaned_token)
        self.library_key: str | None = None  # Set externally via attribute assignment

    def discover(self) -> list[DiscoveredItem]:
        """
        Discover content items from the Plex server.

        Returns:
            List of discovered content items

        Raises:
            ImporterError: If discovery fails
            ImporterConnectionError: If cannot connect to Plex server
        """
        try:
            # Test connection first
            if not self._test_connection():
                raise ImporterConnectionError("Cannot connect to Plex server")

            discovered_items = []
            libraries = self.client.get_libraries()
            # If scoped to a specific library, filter to that key
            if self.library_key is not None:
                libraries = [
                    lib for lib in libraries if str(lib.get("key")) == str(self.library_key)
                ]

            for library in libraries:
                try:
                    items = self.client.get_library_items(library["key"])
                    for item in items:
                        discovered_item = self._create_discovered_item(item, library)
                        if discovered_item:
                            discovered_items.append(discovered_item)
                except Exception as e:
                    logger.warning(f"Failed to discover items from library {library['title']}: {e}")
                    continue

            return discovered_items

        except Exception as e:
            raise ImporterError(f"Failed to discover content from Plex: {str(e)}") from e

    # Optional fast path for targeted ingest
    def discover_scoped(
        self, *, title: str | None = None, season: int | None = None, episode: int | None = None
    ) -> list[DiscoveredItem]:
        """
        Discover only items that match the provided scope when possible.

        For TV libraries, this uses filtered library enumeration to avoid scanning
        the entire library hierarchy.
        """
        try:
            discovered_items: list[DiscoveredItem] = []

            # If we have a library_key, use filtered enumeration
            if self.library_key is not None:
                items = self.client.get_library_items(
                    self.library_key,
                    title_filter=title,
                    season_filter=season,
                    episode_filter=episode,
                )
                for item in items:
                    di = self._create_discovered_item(item, {"title": "scoped", "key": self.library_key})
                    if di:
                        discovered_items.append(di)
                return discovered_items

            # Fallback: try series search path when full library filter isn't available
            if title and season is not None and episode is not None:
                ep = self.client.find_episode_by_sse(title, season, episode)
                # Synthesize a minimal item compatible with _create_discovered_item
                # Try to fetch file info via get_episode_metadata to get Part file
                rk_val = ep.get("ratingKey")
                meta = self.client.get_episode_metadata(int(str(rk_val))) if rk_val is not None else {}
                part_file = None
                file_size = None
                for media in meta.get("Media", []):
                    for part in media.get("Part", []):
                        if part.get("file"):
                            part_file = part.get("file")
                            file_size = part.get("size")
                            break
                    if part_file:
                        break
                synth = {
                    "ratingKey": ep.get("ratingKey"),
                    "title": ep.get("title"),
                    "type": "episode",
                    "file_path": part_file,
                    "fileSize": file_size,
                    "updatedAt": ep.get("updatedAt"),
                    "show_title": ep.get("grandparentTitle"),
                    "season_index": ep.get("parentIndex"),
                    "episode_index": ep.get("index"),
                }
                di = self._create_discovered_item(synth, {"title": "scoped"})
                return [di] if di else []

            # Last resort: standard discovery
            return self.discover()
        except Exception as e:
            raise ImporterError(f"Failed to discover content from Plex: {str(e)}") from e

    # Contract hook used by collection ingest to validate ingestibility before discovery
    def validate_ingestible(self, collection: Collection) -> bool:
        """
        Return True if this importer can attempt ingest for the given collection.

        For Plex, a lightweight connectivity check is sufficient here; deeper
        path mapping validation is handled elsewhere in the CLI/service layer.
        """
        try:
            return bool(self._test_connection())
        except Exception:
            return False

    @classmethod
    def get_config_schema(cls) -> ImporterConfig:
        """
        Return the configuration schema for the Plex importer.

        Returns:
            ImporterConfig object defining the configuration schema
        """
        return ImporterConfig(
            required_params=[
                {
                    "name": "base_url",
                    "description": "Base URL for the Plex server (e.g., http://192.168.1.100:32400)",
                },
                {"name": "token", "description": "Plex authentication token"},
            ],
            optional_params=[],
            description="Connect to Plex Media Server instances and discover content from their libraries",
        )

    @classmethod
    def get_update_fields(cls) -> list[UpdateFieldSpec]:
        """
        Return the list of updatable configuration fields for the Plex importer.

        Returns:
            List of UpdateFieldSpec objects describing updatable fields
        """
        return [
            UpdateFieldSpec(
                config_key="base_url",
                cli_flag="--base-url",
                help="Plex server base URL (e.g., http://192.168.1.100:32400)",
                field_type="string",
                is_sensitive=False,
                is_immutable=False,
            ),
            UpdateFieldSpec(
                config_key="token",
                cli_flag="--token",
                help="Plex authentication token",
                field_type="string",
                is_sensitive=True,
                is_immutable=False,
            ),
            UpdateFieldSpec(
                config_key="servers",
                cli_flag="--servers",
                help="JSON array of server definitions",
                field_type="json",
                is_sensitive=False,
                is_immutable=False,
            ),
        ]

    @classmethod
    def validate_partial_update(cls, partial_config: dict[str, Any]) -> None:
        """
        Validate a partial configuration update for the Plex importer.

        Args:
            partial_config: Dictionary containing only the fields being updated

        Raises:
            ImporterConfigurationError: If validation fails
        """
        if "base_url" in partial_config:
            url = partial_config["base_url"]
            if not isinstance(url, str):
                raise ImporterConfigurationError("base_url must be a string")
            if not url.startswith(("http://", "https://")):
                raise ImporterConfigurationError("base_url must start with http:// or https://")

        if "token" in partial_config:
            token = partial_config["token"]
            if not isinstance(token, str):
                raise ImporterConfigurationError("token must be a string")
            if not token:
                raise ImporterConfigurationError("token cannot be empty")

        if "servers" in partial_config:
            servers = partial_config["servers"]
            if not isinstance(servers, list):
                raise ImporterConfigurationError("servers must be a JSON array")

    def _validate_parameter_types(self) -> None:
        """
        Validate configuration parameter types and values.

        Raises:
            ImporterConfigurationError: If configuration parameters are invalid
        """
        # Validate base_url
        base_url = self._safe_get_config("base_url")
        if not base_url or not isinstance(base_url, str):
            raise ImporterConfigurationError(
                "base_url configuration parameter must be a non-empty string"
            )

        if not base_url.startswith(("http://", "https://")):
            raise ImporterConfigurationError(
                "base_url configuration parameter must be a valid HTTP/HTTPS URL"
            )

        # Validate token
        token = self._safe_get_config("token")
        if not token or not isinstance(token, str):
            raise ImporterConfigurationError(
                "token configuration parameter must be a non-empty string"
            )

    def _get_examples(self) -> list[str]:
        """
        Get example usage strings for the Plex importer.

        Returns:
            List of example usage strings
        """
        return [
            'retrovue source add --type plex --name "My Plex Server" --base-url "http://192.168.1.100:32400" --token "your-plex-token"'
        ]

    def _get_cli_params(self) -> dict[str, str]:
        """
        Get CLI parameter descriptions for the Plex importer.

        Returns:
            Dictionary mapping parameter names to descriptions
        """
        return {
            "name": "Friendly name for the Plex server",
            "base_url": "Base URL for the Plex server (e.g., http://192.168.1.100:32400)",
            "token": "Plex authentication token",
        }

    def list_asset_groups(self) -> list[dict[str, Any]]:
        """
        List the asset groups (libraries) available from this Plex source.

        Returns:
            List of dictionaries containing library information
        """
        try:
            libraries = self.client.get_libraries()

            asset_groups = []
            for lib in libraries:
                # Count items in this library
                try:
                    items = self.client.get_library_items(lib["key"])
                    asset_count = len(items)
                except Exception:
                    asset_count = 0

                asset_groups.append(
                    {
                        "id": lib["key"],
                        "name": lib["title"],
                        "path": f"plex://{lib['key']}",
                        "enabled": True,  # Default to enabled, actual state managed by database
                        "asset_count": asset_count,
                        "type": lib.get("type", "unknown"),
                    }
                )

            return asset_groups

        except Exception as e:
            raise ImporterError(f"Failed to list asset groups: {str(e)}") from e

    def enable_asset_group(self, group_id: str) -> bool:
        """
        Enable an asset group (library) for content discovery.

        Args:
            group_id: Library key

        Returns:
            True if successfully enabled, False otherwise
        """
        try:
            # For Plex, we just verify the library exists
            libraries = self.client.get_libraries()
            return any(lib["key"] == group_id for lib in libraries)

        except Exception as e:
            logger.warning(f"Failed to enable asset group {group_id}: {e}")
            return False

    def disable_asset_group(self, group_id: str) -> bool:
        """
        Disable an asset group (library) from content discovery.

        Args:
            group_id: Library key

        Returns:
            True if successfully disabled, False otherwise
        """
        # For Plex, disabling is handled at the database level
        # This method just confirms the operation
        return True

    def _test_connection(self) -> bool:
        """
        Test connection to the Plex server.

        Returns:
            True if connection is successful, False otherwise
        """
        try:
            libraries = self.client.get_libraries()
            return len(libraries) >= 0  # Even empty libraries list means connection works
        except Exception:
            return False

    def _create_discovered_item(
        self, item: dict[str, Any], library: dict[str, Any]
    ) -> DiscoveredItem | None:
        """
        Create a DiscoveredItem from a Plex item.

        Args:
            item: Plex item information
            library: Library information

        Returns:
            DiscoveredItem or None if creation fails
        """
        try:
            # Always use source-native URI as the item's path_uri
            # Keep upstream file path available on the item for resolver use
            plex_file_path = item.get("file_path", "")
            path_uri = f"plex://{item.get('ratingKey', 'unknown')}"

            # Extract metadata
            title = item.get("title", "Unknown Title")
            year = item.get("year")
            file_size = item.get("fileSize")

            # Extract TV show hierarchy information
            series_title = item.get("show_title")
            season_number = item.get("season_index")
            episode_number = item.get("episode_index")

            # Create raw labels
            raw_labels = []
            raw_labels.append(f"title:{title}")

            if year:
                raw_labels.append(f"year:{year}")

            if series_title:
                raw_labels.append(f"series:{series_title}")

            if season_number:
                raw_labels.append(f"season:{season_number}")

            if episode_number:
                raw_labels.append(f"episode:{episode_number}")

            raw_labels.append(f"library:{library['title']}")
            # Keep upstream file path and library metadata to assist URI resolution later
            if plex_file_path:
                raw_labels.append(f"plex_file_path:{plex_file_path}")
            if "key" in library:
                raw_labels.append(f"plex_library_key:{library['key']}")
            raw_labels.append(f"type:{item.get('type', 'unknown')}")

            # Convert updatedAt to datetime if available
            last_modified = None
            if item.get("updatedAt"):
                try:
                    last_modified = datetime.fromtimestamp(int(item["updatedAt"]))
                except (ValueError, TypeError):
                    pass

            # Always fetch full metadata first, then build editorial from it
            detailed: dict[str, Any] | None = None
            try:
                rk_val = item.get("ratingKey")
                if rk_val is not None:
                    # Use episode-compatible shim (delegates to generic)
                    detailed = self.client.get_episode_metadata(int(str(rk_val))) or {}
            except Exception as e:
                logger.warning(
                    f"Plex detailed metadata fetch failed for ratingKey={item.get('ratingKey')}: {e}"
                )
                detailed = {}

            # Build editorial from detailed metadata, falling back to listing item
            editorial: dict[str, Any] = {}
            meta: dict[str, Any] = detailed or {}
            editorial["title"] = meta.get("title") or title
            if meta.get("originalTitle"):
                editorial["original_title"] = meta.get("originalTitle")
            if meta.get("year") or year:
                try:
                    _yr = meta.get("year") or year
                    if _yr is not None:
                        editorial["production_year"] = int(str(_yr))
                except Exception:
                    pass
            if meta.get("originallyAvailableAt"):
                editorial["release_date"] = meta.get("originallyAvailableAt")
            # Description
            editorial["description"] = meta.get("summary") or item.get("summary")
            # Content rating
            cr = meta.get("content_rating") or meta.get("contentRating") or item.get("contentRating")
            if cr:
                editorial["content_rating"] = {"system": "PLEX", "code": cr}
            # Studio
            if meta.get("studio"):
                editorial["studio"] = meta.get("studio")
            # Countries
            try:
                countries = meta.get("country_tags") or [
                    c.get("tag") for c in meta.get("Country", []) if c.get("tag")
                ]
                if countries:
                    editorial["countries"] = countries
            except Exception:
                pass
            # Genres
            try:
                genres = meta.get("genres") or []
                if not genres:
                    genres = [g.get("tag") for g in meta.get("Genre", []) if g.get("tag")]
                if genres:
                    editorial["genres"] = genres
            except Exception:
                pass
            # Collections
            try:
                collections = meta.get("collection_tags") or [
                    c.get("tag") for c in meta.get("Collection", []) if c.get("tag")
                ]
                if collections:
                    editorial["collections"] = collections
            except Exception:
                pass
            # Directors, Writers, Cast
            try:
                directors = meta.get("director_tags") or [
                    d.get("tag") for d in meta.get("Director", []) if d.get("tag")
                ]
                if directors:
                    editorial["directors"] = directors
            except Exception:
                pass
            try:
                writers = meta.get("writer_tags") or [
                    w.get("tag") for w in meta.get("Writer", []) if w.get("tag")
                ]
                if writers:
                    editorial["writers"] = writers
            except Exception:
                pass
            try:
                cast = meta.get("cast_tags") or [
                    r.get("tag") for r in meta.get("Role", []) if r.get("tag")
                ]
                if cast:
                    editorial["cast"] = cast
            except Exception:
                pass
            # Runtime (ms and seconds)
            try:
                dur_ms = meta.get("duration")
                if dur_ms is None:
                    media_list = meta.get("Media") or []
                    if media_list and isinstance(media_list[0], dict):
                        dur_ms = media_list[0].get("duration")
                if dur_ms is not None:
                    editorial["runtime_ms"] = int(dur_ms)
                    editorial["runtime_seconds"] = int(dur_ms) // 1000
            except Exception:
                pass
            # Episode/Show specifics
            if series_title or meta.get("grandparentTitle") or meta.get("parentTitle"):
                editorial["series_title"] = (
                    meta.get("grandparentTitle")
                    or meta.get("parentTitle")
                    or series_title
                )
            try:
                _pidx = meta.get("parentIndex")
                if _pidx is not None:
                    editorial["season_number"] = int(str(_pidx))
            except Exception:
                pass
            try:
                _eidx = meta.get("index")
                if _eidx is not None:
                    editorial["episode_number"] = int(str(_eidx))
            except Exception:
                pass
            # Library name for operator visibility (can be ignored downstream if redundant)
            if library.get("title"):
                editorial["library_name"] = library.get("title")

            # Debug output removed

            # Populate content rating from item if present
            cr_item = item.get("contentRating")
            if cr_item:
                editorial["content_rating"] = {"system": "TV", "code": cr_item}

            # Try to populate genres/summary/contentRating from detailed metadata only if missing
            # Always attempt a per-item metadata fetch and merge rich fields
            # Label whether detailed metadata was present
            try:
                rk = item.get("ratingKey")
                if rk is not None:
                    meta = detailed or {}
                    has_details = bool(
                        isinstance(meta, dict)
                        and (meta.get("summary") or meta.get("contentRating") or (meta.get("genres") or []))
                    )
                    raw_labels.append("plex_meta:ok" if has_details else "plex_meta:empty")
            except Exception:
                pass
            # Remove None values
            editorial = {k: v for k, v in editorial.items() if v is not None}

            return DiscoveredItem(
                path_uri=path_uri,
                provider_key=item.get("ratingKey"),
                raw_labels=raw_labels,
                last_modified=last_modified,
                size=int(file_size) if file_size else None,
                hash_sha256=None,  # Plex doesn't provide file hashes
                editorial=editorial,
                sidecar=None,
                source_payload=detailed or {},
            )

        except Exception as e:
            logger.warning(
                f"Failed to create discovered item from Plex item {item.get('ratingKey', 'unknown')}: {e}"
            )
            return None

    def resolve_local_uri(
        self,
        item: DiscoveredItem | dict,
        *,
        collection: Any | None = None,
        path_mappings: list[tuple[str, str]] | None = None,
    ) -> str:
        """
        Resolve a local file:// URI using Plex library locations and PathMappings.

        Steps:
        - Determine the file path for the item (from labels or metadata lookup)
        - Find the item's library and compute the relative suffix from a library location
        - Build a virtual plex path "/plex/{library_name_normalized}{suffix}"
        - Apply longest-prefix match from path_mappings to map to local path
        - Return file:// URI to the mapped local path
        """
        try:
            # Extract upstream file path from labels when available
            def _labels(obj: DiscoveredItem | dict) -> list[str]:
                if isinstance(obj, dict):
                    return obj.get("raw_labels") or []
                return getattr(obj, "raw_labels", None) or []

            file_path = None
            lib_key = None
            for lbl in _labels(item):
                if isinstance(lbl, str):
                    if lbl.startswith("plex_file_path:"):
                        file_path = lbl.split(":", 1)[1]
                    elif lbl.startswith("plex_library_key:"):
                        lib_key = lbl.split(":", 1)[1]

            # If no file path in labels, try to look up via ratingKey using metadata call
            if not file_path:
                try:
                    rk = None
                    if isinstance(item, dict):
                        rk = item.get("provider_key") or item.get("ratingKey")
                    else:
                        rk = getattr(item, "provider_key", None)
                    if rk:
                        meta = self.client.get_episode_metadata(int(str(rk)))
                        # Find first Part file
                        for media in meta.get("Media", []):
                            for part in media.get("Part", []):
                                if part.get("file"):
                                    file_path = part.get("file")
                                    break
                            if file_path:
                                break
                except Exception:
                    file_path = None

            if not file_path:
                return ""

            # Build mapping candidates: (source_path_string, is_virtual)
            candidates: list[str] = []
            try:
                # Determine virtual /plex/{collection_name} path using the RetroVue collection name
                suffix = None
                if collection is not None and hasattr(collection, "name"):
                    # Normalize collection name to match PathMapping convention (lowercase + underscores)
                    coll_name = str(collection.name)
                    coll_name = coll_name.strip().lower().replace(" ", "_")
                else:
                    coll_name = "unknown"
                # Try to compute suffix from Plex library locations to strip root
                try:
                    libraries = self.client.get_libraries()
                    if lib_key:
                        for lib in libraries:
                            if str(lib.get("key")) == str(lib_key):
                                for loc in lib.get("locations", []) or []:
                                    if isinstance(loc, str) and file_path.startswith(loc):
                                        suffix = file_path[len(loc) :]
                                        break
                                break
                except Exception:
                    suffix = None
                if suffix is None:
                    from pathlib import Path as _Path
                    suffix = "/" + _Path(file_path).name
                suffix = suffix.replace("\\", "/")
                virt_plex_path = f"/plex/{coll_name}{suffix}"
                candidates.append(virt_plex_path)
            except Exception:
                pass

            # Also try mapping the raw Plex file path directly
            try:
                raw_norm = file_path.replace("\\", "/")
                candidates.append(raw_norm)
            except Exception:
                pass

            # Apply path mappings (longest-prefix match against any candidate)
            if path_mappings and candidates:
                def _norm(s: str) -> str:
                    t = s.replace("\\", "/")
                    # strip schemes and leading slashes
                    for pref in ("file://", "smb://"):
                        if t.lower().startswith(pref):
                            t = t[len(pref) :]
                            break
                    while t.startswith("/"):
                        t = t[1:]
                    return t.lower()
                def _to_file_uri_preserve(path_str: str) -> str:
                    # Preserve drive letters; convert UNC appropriately
                    p = path_str.replace("\\", "/")
                    # UNC: //server/share/...
                    if p.startswith("//"):
                        return f"file:{p}"
                    # Drive letter: R:/...
                    if len(p) >= 2 and p[1] == ":":
                        if not p.startswith("/"):
                            p = "/" + p
                        return f"file://{p}"
                    # POSIX
                    if not p.startswith("/"):
                        p = "/" + p
                    return f"file://{p}"
                best: tuple[str, str, str] | None = None  # (matched_prefix, local_base, chosen_candidate)
                for candidate in candidates:
                    cand_lower = _norm(candidate)
                    for plex_p, local_p in path_mappings:
                        plex_norm = _norm(plex_p)
                        if cand_lower.startswith(plex_norm):
                            if best is None or len(plex_norm) > len(best[0]):
                                best = (plex_norm, local_p, candidate)
                if best is not None:
                    matched_prefix, local_p, chosen = best
                    # Compute remainder using normalized forms to avoid slash/case issues
                    chosen_norm = _norm(chosen)
                    remainder = chosen_norm[len(matched_prefix) :]
                    from pathlib import Path as _Path

                    # Return native OS path (do NOT convert to file://)
                    mapped_path = str(_Path(local_p) / remainder.lstrip("/\\"))
                    return mapped_path

            return ""
        except Exception:
            return ""

    def list_collections(self, source_config: dict[str, Any]) -> list[dict[str, Any]]:
        """
        Return the collections (libraries) available in that source.

        Args:
            source_config: Source configuration (unused for Plex)

        Returns:
            List of collections with stable identifier, display name, source path, and filesystem locations
        """
        try:
            libraries = self.client.get_libraries()

            collections = []
            for lib in libraries:
                collections.append(
                    {
                        "external_id": lib["key"],
                        "name": lib["title"],
                        "type": lib.get("type", "unknown"),
                        "plex_section_ref": f"plex://{lib['key']}",
                        "locations": lib.get("locations", []),
                    }
                )

            return collections

        except ImporterError:
            # Re-raise ImporterError as-is to avoid duplicate error messages
            raise
        except Exception as e:
            logger.error(f"Failed to list collections: {e}")
            raise ImporterError(f"Failed to list collections: {e}") from e
