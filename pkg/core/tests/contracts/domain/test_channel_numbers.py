"""
Contract tests for channel number validation.

Verifies that channel numbers from configuration are:
  - unique across channels
  - positive integers
  - propagated correctly to the channel model and Plex adapter
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from retrovue.infra.exceptions import ConfigurationError
from retrovue.runtime.providers import YamlChannelConfigProvider


def test_channel_numbers_must_be_unique():
    """Duplicate channel number MUST raise ConfigurationError."""
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        (d / "ch1.yaml").write_text("channel: ch1\nnumber: 101\nname: Ch1\n")
        (d / "ch2.yaml").write_text("channel: ch2\nnumber: 101\nname: Ch2\n")
        with pytest.raises(ConfigurationError) as exc_info:
            YamlChannelConfigProvider(d).to_channels_list()
        assert "Duplicate channel number" in str(exc_info.value)
        assert "101" in str(exc_info.value)


def test_channel_numbers_must_be_positive():
    """Channel number MUST be > 0."""
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        (d / "ch1.yaml").write_text("channel: ch1\nnumber: 0\nname: Ch1\n")
        with pytest.raises(ConfigurationError) as exc_info:
            YamlChannelConfigProvider(d).to_channels_list()
        assert "positive" in str(exc_info.value).lower()


def test_channel_numbers_must_be_integer():
    """Channel number MUST be an integer."""
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        (d / "ch1.yaml").write_text("channel: ch1\nnumber: 101.5\nname: Ch1\n")
        with pytest.raises(ConfigurationError) as exc_info:
            YamlChannelConfigProvider(d).to_channels_list()
        assert "integer" in str(exc_info.value).lower()


def test_channel_number_propagates_to_channels_list():
    """Configured number MUST appear in to_channels_list as 'number'."""
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        (d / "ch1.yaml").write_text("channel: ch1\nnumber: 201\nname: Ch1\n")
        provider = YamlChannelConfigProvider(d)
        channels = provider.to_channels_list()
        assert len(channels) == 1
        assert channels[0]["number"] == 201
        assert channels[0]["channel_id"] == "ch1"


def test_channel_number_required_raises_when_missing():
    """Missing both 'number' and 'channel_number' MUST raise ConfigurationError."""
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        (d / "ch1.yaml").write_text("channel: ch1\nname: Ch1\n")
        with pytest.raises(ConfigurationError) as exc_info:
            YamlChannelConfigProvider(d).to_channels_list()
        assert "Missing" in str(exc_info.value)
        assert "number" in str(exc_info.value).lower()


def test_channel_number_backward_compat_channel_number_key():
    """Loader MUST accept legacy 'channel_number' when 'number' is missing."""
    with tempfile.TemporaryDirectory() as tmp:
        d = Path(tmp)
        (d / "ch1.yaml").write_text("channel: ch1\nchannel_number: 301\nname: Ch1\n")
        provider = YamlChannelConfigProvider(d)
        channels = provider.to_channels_list()
        assert len(channels) == 1
        assert channels[0]["number"] == 301
