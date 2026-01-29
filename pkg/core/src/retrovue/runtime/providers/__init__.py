"""
Channel configuration providers.

Provides implementations of ChannelConfigProvider for loading
channel configurations from various sources.
"""

from .file_config_provider import FileChannelConfigProvider

__all__ = [
    "FileChannelConfigProvider",
]
