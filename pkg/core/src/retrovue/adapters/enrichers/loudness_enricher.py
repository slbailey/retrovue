"""
Loudness enricher for broadcast-standard audio normalization.

INV-LOUDNESS-NORMALIZED-001: Measures integrated loudness via ffmpeg ebur128
and computes gain_db = target_lufs - integrated_lufs. The result is stored in
the probed payload under the "loudness" key.

Target: -24 LUFS integrated (ATSC A/85).
"""

from __future__ import annotations

import re
import subprocess
from typing import Any

from ..importers.base import DiscoveredItem
from .base import BaseEnricher, EnricherConfig, EnricherError

# ATSC A/85 target (CALM Act, US broadcast standard)
TARGET_LUFS: float = -24.0

# Regex to parse integrated loudness from ffmpeg ebur128 stderr
_INTEGRATED_RE = re.compile(r"I:\s+([-\d.]+)\s+LUFS")


def compute_gain_db(integrated_lufs: float) -> float:
    """Compute loudness normalization gain.

    Rule 7: gain_db = target_lufs - integrated_lufs
    """
    return TARGET_LUFS - integrated_lufs


def get_gain_db_from_probed(probed: dict[str, Any] | None) -> float:
    """Extract gain_db from probed payload. Returns 0.0 if absent."""
    if not probed:
        return 0.0
    loudness = probed.get("loudness")
    if not loudness or not isinstance(loudness, dict):
        return 0.0
    return float(loudness.get("gain_db", 0.0))


def needs_loudness_measurement(probed: dict[str, Any] | None) -> bool:
    """Check whether an asset needs loudness measurement."""
    if not probed:
        return True
    loudness = probed.get("loudness")
    if not loudness or not isinstance(loudness, dict):
        return True
    return "gain_db" not in loudness


class LoudnessEnricher(BaseEnricher):
    """Measures integrated loudness via ffmpeg ebur128 and computes gain_db.

    Stores result in discovered_item.probed["loudness"]:
        {"integrated_lufs": float, "gain_db": float, "target_lufs": -24.0}
    """

    name = "loudness"
    scope = "ingest"

    def __init__(self, ffmpeg_path: str = "ffmpeg", timeout: int = 120) -> None:
        super().__init__(ffmpeg_path=ffmpeg_path, timeout=timeout)
        self.ffmpeg_path = ffmpeg_path
        self.timeout = timeout

    def enrich(self, discovered_item: DiscoveredItem) -> DiscoveredItem:
        """Enrich a discovered item with loudness measurement."""
        raw = getattr(discovered_item, "path_uri", "") or ""
        if not raw:
            return discovered_item

        # Resolve file path from URI
        file_path = raw
        if raw.startswith("file://"):
            from urllib.parse import unquote, urlparse
            parsed = urlparse(raw)
            file_path = unquote(parsed.path or raw[7:])

        try:
            loudness = self.measure_loudness(file_path)
        except EnricherError:
            raise
        except Exception as e:
            raise EnricherError(f"Loudness measurement failed: {e}") from e

        existing_probed = getattr(discovered_item, "probed", None) or {}
        merged_probed = dict(existing_probed)
        merged_probed["loudness"] = loudness

        return DiscoveredItem(
            path_uri=discovered_item.path_uri,
            provider_key=discovered_item.provider_key,
            raw_labels=discovered_item.raw_labels,
            last_modified=discovered_item.last_modified,
            size=discovered_item.size,
            hash_sha256=discovered_item.hash_sha256,
            editorial=getattr(discovered_item, "editorial", None),
            sidecar=getattr(discovered_item, "sidecar", None),
            source_payload=getattr(discovered_item, "source_payload", None),
            probed=merged_probed,
        )

    def measure_loudness(self, file_path: str) -> dict[str, Any]:
        """Run ffmpeg ebur128 measurement and return loudness dict.

        Returns:
            {"integrated_lufs": float, "gain_db": float, "target_lufs": -24.0}
        """
        cmd = [
            self.ffmpeg_path,
            "-i", file_path,
            "-af", "ebur128",
            "-f", "null",
            "-",
        ]

        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=self.timeout,
        )

        if result.returncode != 0:
            raise EnricherError(f"ffmpeg ebur128 failed: {result.stderr[:500]}")

        # The summary block appears at the end of stderr. Per-moment I: lines
        # appear throughout. Extract only the summary section to avoid matching
        # early running-average values (often -70 LUFS at start of file).
        summary_idx = result.stderr.rfind("Summary:")
        search_text = result.stderr[summary_idx:] if summary_idx >= 0 else result.stderr
        match = _INTEGRATED_RE.search(search_text)
        if not match:
            raise EnricherError(
                "Could not parse integrated loudness from ffmpeg ebur128 output"
            )

        integrated_lufs = float(match.group(1))
        gain_db = compute_gain_db(integrated_lufs)

        return {
            "integrated_lufs": integrated_lufs,
            "gain_db": gain_db,
            "target_lufs": TARGET_LUFS,
        }

    @classmethod
    def get_config_schema(cls) -> EnricherConfig:
        return EnricherConfig(
            required_params=[],
            optional_params=[
                {
                    "name": "ffmpeg_path",
                    "description": "Path to the ffmpeg executable",
                    "default": "ffmpeg",
                },
                {
                    "name": "timeout",
                    "description": "Timeout in seconds for loudness measurement",
                    "default": "120",
                },
            ],
            scope=cls.scope,
            description="Measures integrated loudness (EBU R128) and computes ATSC A/85 normalization gain",
        )

    def _validate_parameter_types(self) -> None:
        ffmpeg_path = self._safe_get_config("ffmpeg_path")
        if ffmpeg_path is not None and (not isinstance(ffmpeg_path, str) or not ffmpeg_path.strip()):
            from .base import EnricherConfigurationError
            raise EnricherConfigurationError("ffmpeg_path must be a non-empty string")
        timeout = self._safe_get_config("timeout", 120)
        if not isinstance(timeout, int) or timeout <= 0:
            from .base import EnricherConfigurationError
            raise EnricherConfigurationError("timeout must be a positive integer")
