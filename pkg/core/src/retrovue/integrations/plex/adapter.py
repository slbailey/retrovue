"""
Re-export PlexAdapter for canonical import path.

Contract tests import from retrovue.integrations.plex.adapter.
"""

from retrovue.integrations.plex.service import PlexAdapter

__all__ = ["PlexAdapter"]
