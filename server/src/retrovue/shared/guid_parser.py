"""
GUID Parser and Normalization for Retrovue

This module handles parsing and normalizing external identifiers (GUIDs) from Plex metadata.
It supports disambiguation of series with the same title but different years by using
stable external identifiers from various providers.

Key Features:
- Parse Plex GUID format into provider/external_id pairs
- Support for TVDB, TMDB, IMDB, and Plex internal GUIDs
- Normalize GUIDs for consistent storage and lookup
- Handle multiple GUIDs per show for robust identification

Example GUID formats:
- com.plexapp.agents.thetvdb://12345 → (tvdb, 12345)
- com.plexapp.agents.themoviedb://54321 → (tmdb, 54321)
- imdb://tt0123456 → (imdb, tt0123456)
- plex://show/abcdef → (plex, show/abcdef)
"""

import re


class GUIDParser:
    """Parser for Plex GUIDs and external identifiers"""

    # Provider mapping patterns
    PROVIDER_PATTERNS = {
        "tvdb": [
            r"com\.plexapp\.agents\.thetvdb://(\d+)",
            r"tvdb://(\d+)",
            r"thetvdb://(\d+)",
        ],
        "tmdb": [
            r"com\.plexapp\.agents\.themoviedb://(\d+)",
            r"tmdb://(\d+)",
            r"themoviedb://(\d+)",
        ],
        "imdb": [r"imdb://(tt\d+)", r"com\.plexapp\.agents\.imdb://(tt\d+)"],
        "plex": [r"plex://(show/[^/]+)", r"plex://(movie/[^/]+)"],
    }

    @classmethod
    def parse_guid(cls, guid: str) -> tuple[str, str] | None:
        """
        Parse a Plex GUID into provider and external_id.

        Args:
            guid: The GUID string from Plex metadata

        Returns:
            Tuple of (provider, external_id) or None if not parseable
        """
        if not guid:
            return None

        for provider, patterns in cls.PROVIDER_PATTERNS.items():
            for pattern in patterns:
                match = re.match(pattern, guid, re.IGNORECASE)
                if match:
                    return (provider, match.group(1))

        return None

    @classmethod
    def parse_guids(cls, guids: list[str]) -> list[tuple[str, str]]:
        """
        Parse multiple GUIDs into provider/external_id pairs.

        Args:
            guids: List of GUID strings from Plex metadata

        Returns:
            List of (provider, external_id) tuples
        """
        parsed_guids = []
        for guid in guids:
            parsed = cls.parse_guid(guid)
            if parsed:
                parsed_guids.append(parsed)
        return parsed_guids

    @classmethod
    def get_primary_guid(cls, guids: list[str]) -> str | None:
        """
        Get the primary GUID from a list, preferring TVDB > TMDB > IMDB > Plex.

        Args:
            guids: List of GUID strings

        Returns:
            The primary GUID string or None
        """
        parsed_guids = cls.parse_guids(guids)

        # Priority order: tvdb > tmdb > imdb > plex
        priority_order = ["tvdb", "tmdb", "imdb", "plex"]

        for provider in priority_order:
            for parsed_provider, external_id in parsed_guids:
                if parsed_provider == provider:
                    # Reconstruct the original GUID format
                    if provider == "tvdb":
                        return f"com.plexapp.agents.thetvdb://{external_id}"
                    elif provider == "tmdb":
                        return f"com.plexapp.agents.themoviedb://{external_id}"
                    elif provider == "imdb":
                        return f"imdb://{external_id}"
                    elif provider == "plex":
                        return f"plex://{external_id}"

        return None

    @classmethod
    def normalize_guid(cls, guid: str) -> str:
        """
        Normalize a GUID to a standard format.

        Args:
            guid: The GUID string to normalize

        Returns:
            Normalized GUID string
        """
        parsed = cls.parse_guid(guid)
        if not parsed:
            return guid

        provider, external_id = parsed

        # Return in standard format
        if provider == "tvdb":
            return f"com.plexapp.agents.thetvdb://{external_id}"
        elif provider == "tmdb":
            return f"com.plexapp.agents.themoviedb://{external_id}"
        elif provider == "imdb":
            return f"imdb://{external_id}"
        elif provider == "plex":
            return f"plex://{external_id}"

        return guid


def extract_guids_from_plex_metadata(metadata: dict) -> list[str]:
    """
    Extract GUIDs from Plex metadata structure.

    Args:
        metadata: Plex metadata dictionary

    Returns:
        List of GUID strings
    """
    guids = []

    # Check for direct guid field
    if "guid" in metadata:
        guids.append(metadata["guid"])

    # Check for Guid array (multiple GUIDs)
    if "Guid" in metadata:
        for guid_obj in metadata["Guid"]:
            if isinstance(guid_obj, dict) and "id" in guid_obj:
                guids.append(guid_obj["id"])

    return guids


def get_show_disambiguation_key(title: str, year: int | None) -> str:
    """
    Create a disambiguation key for a show.

    Args:
        title: Show title
        year: Show year (optional)

    Returns:
        Disambiguation key string
    """
    if year:
        return f"{title} ({year})"
    else:
        return title


def format_show_for_display(
    title: str, year: int | None, guids: list[tuple[str, str]] | None = None
) -> str:
    """
    Format a show for display with disambiguation information.

    Args:
        title: Show title
        year: Show year (optional)
        guids: List of (provider, external_id) tuples

    Returns:
        Formatted display string
    """
    display = get_show_disambiguation_key(title, year)

    if guids:
        guid_info = []
        for provider, external_id in guids:
            guid_info.append(f"{provider.upper()}:{external_id}")
        display += f" [{' '.join(guid_info)}]"

    return display
