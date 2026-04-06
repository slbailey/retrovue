"""Test fixtures for channel_stream — FakeTsSource.

Moved from retrovue.runtime.channel_stream to satisfy
INV-PRODUCTION-BOUNDARY-001.
"""
from __future__ import annotations

import socket
from typing import Optional


class FakeTsSource:
    """Fake TS source for tests (generates dummy TS data)."""

    def __init__(self, chunk_size: int = 188 * 10):
        self.chunk_size = chunk_size
        self._closed = False

    def read(self, size: int) -> bytes:
        """Generate fake TS data."""
        if self._closed:
            return b""
        # Generate minimal valid TS packet header + payload
        # TS packet = 188 bytes: sync byte (0x47) + header + payload
        chunk = b"\x47" + b"\x00" * min(size - 1, 187)
        if size > 188:
            # Multiple TS packets
            packets_needed = (size + 187) // 188
            chunk = chunk * packets_needed
            chunk = chunk[:size]
        return chunk

    def close(self) -> None:
        """Mark source as closed."""
        self._closed = True

    def get_socket(self) -> Optional[socket.socket]:
        return None
