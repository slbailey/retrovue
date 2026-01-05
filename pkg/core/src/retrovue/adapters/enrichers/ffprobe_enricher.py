"""
FFprobe enricher for extracting media metadata.

This enricher uses FFprobe to extract technical metadata from media files,
including duration, codecs, container format, and chapter markers.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from ..importers.base import DiscoveredItem
from .base import BaseEnricher, EnricherConfig, EnricherConfigurationError, EnricherError


class FFprobeEnricher(BaseEnricher):
    """
    Enricher that extracts technical metadata from media files using FFprobe.

    This enricher analyzes media files using FFprobe and extracts technical
    metadata including duration, codecs, container format, and chapter markers.
    """

    name = "ffprobe"
    scope = "ingest"

    def __init__(self, ffprobe_path: str = "ffprobe", timeout: int = 30):
        """
        Initialize the FFprobe enricher.

        Args:
            ffprobe_path: Path to the ffprobe executable
            timeout: Timeout in seconds for FFprobe operations
        """
        super().__init__(ffprobe_path=ffprobe_path, timeout=timeout)
        self.ffprobe_path = ffprobe_path
        self.timeout = timeout

    def enrich(self, discovered_item: DiscoveredItem) -> DiscoveredItem:
        """
        Enrich a discovered item with FFprobe metadata.

        Args:
            discovered_item: The item to enrich

        Returns:
            The enriched item

        Raises:
            EnricherError: If enrichment fails
        """
        try:
            # Accept either file:// URIs or direct filesystem paths
            raw = getattr(discovered_item, "path_uri", "") or ""
            if not raw:
                return discovered_item

            file_path: Path | None = None

            if raw.startswith("file://"):
                # Extract file path from URI (robustly parse and unquote)
                parsed = urlparse(raw)
                # Prefer parsed.path; on Windows a leading "/C:/..." may be present
                path_str = unquote(parsed.path or raw[7:])
                # Normalize Windows drive form: "/C:/..." -> "C:/..."
                if path_str.startswith("/") and len(path_str) > 3 and path_str[2] == ":":
                    path_str = path_str[1:]
                file_path = Path(path_str)
            else:
                # Treat as direct filesystem path
                file_path = Path(raw)

            if not file_path.exists():
                raise EnricherError(f"File does not exist: {file_path}")

            # Run FFprobe to get metadata (raw ffprobe JSON)
            metadata = self._run_ffprobe(file_path)

            # Convert metadata to labels
            additional_labels = self._metadata_to_labels(metadata)

            # NEW: build a probed payload from ffprobe
            probed_from_ffprobe = self._metadata_to_probed(metadata)

            # Merge with any existing probed on the item (maybe an importer added some)
            existing_probed = getattr(discovered_item, "probed", None)
            merged_probed = self._deep_merge_dicts(existing_probed, probed_from_ffprobe)

            # finally create the new item – do NOT touch editorial / sidecar
            new_item = DiscoveredItem(
                path_uri=discovered_item.path_uri,
                provider_key=discovered_item.provider_key,
                raw_labels=(discovered_item.raw_labels or []) + additional_labels,
                last_modified=discovered_item.last_modified,
                size=discovered_item.size,
                hash_sha256=discovered_item.hash_sha256,
                editorial=getattr(discovered_item, "editorial", None),
                sidecar=getattr(discovered_item, "sidecar", None),
                source_payload=getattr(discovered_item, "source_payload", None),
                probed=merged_probed,
            )

            return new_item

        except Exception as e:
            raise EnricherError(f"Failed to enrich item: {str(e)}") from e

    @classmethod
    def get_config_schema(cls) -> EnricherConfig:
        """Return configuration schema for the FFprobe enricher."""
        return EnricherConfig(
            required_params=[],
            optional_params=[
                {
                    "name": "ffprobe_path",
                    "description": "Path to the FFprobe executable",
                    "default": "ffprobe",
                },
                {
                    "name": "timeout",
                    "description": "Timeout in seconds for FFprobe operations",
                    "default": "30",
                }
            ],
            scope=cls.scope,
            description="Extracts technical media metadata (duration, codecs, resolution) using FFprobe",
        )

    def _validate_parameter_types(self) -> None:
        """Validate parameter types for the FFprobe enricher."""
        # Validate ffprobe_path is a non-empty string
        ffprobe_path = self._safe_get_config("ffprobe_path")
        if not isinstance(ffprobe_path, str) or not ffprobe_path.strip():
            raise EnricherConfigurationError("ffprobe_path must be a non-empty string")

        # Validate timeout is a positive integer
        timeout = self._safe_get_config("timeout", 30)
        if not isinstance(timeout, int) or timeout <= 0:
            raise EnricherConfigurationError("timeout must be a positive integer")

    def _run_ffprobe(self, file_path: Path) -> dict[str, Any]:
        """
        Run FFprobe on a file and return parsed metadata.

        Args:
            file_path: Path to the media file

        Returns:
            Dictionary containing extracted metadata

        Raises:
            EnricherError: If FFprobe fails
        """
        try:
            # Ensure ffprobe is available
            try:
                import shutil

                if not shutil.which(self.ffprobe_path):
                    raise EnricherError(
                        "FFprobe executable not found. Install ffprobe and ensure it is on PATH, "
                        "or configure ffprobe_path."
                    )
            except EnricherError:
                raise
            except Exception:
                # Fall through to subprocess; FileNotFoundError will be handled explicitly
                pass
            # Build FFprobe command
            cmd = [
                self.ffprobe_path,
                "-v",
                "quiet",
                "-print_format",
                "json",
                "-show_format",
                "-show_streams",
                "-show_chapters",
                str(file_path),
            ]

            # Run FFprobe
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=self.timeout)

            if result.returncode != 0:
                raise EnricherError(f"FFprobe failed: {result.stderr}")

            # Parse JSON output and return the full ffprobe document
            from typing import cast
            data = cast(dict[str, Any], json.loads(result.stdout))

            return data

        except FileNotFoundError:
            raise EnricherError(
                "FFprobe executable not found. Install ffprobe and ensure it is on PATH, or "
                "configure ffprobe_path."
            ) from None
        except subprocess.TimeoutExpired:
            raise EnricherError("FFprobe timed out") from None
        except json.JSONDecodeError as e:
            raise EnricherError(f"Failed to parse FFprobe output: {e}") from e
        except Exception as e:
            raise EnricherError(f"FFprobe execution failed: {e}") from e

    def _deep_merge_dicts(self, base: dict | None, extra: dict | None) -> dict:
        """
        Merge two dicts without losing data. Values from `extra` win only when
        they are scalars; nested dicts are merged recursively.
        """
        if base is None:
            base = {}
        if extra is None:
            return dict(base)

        merged = dict(base)
        for key, val in extra.items():
            if (
                key in merged
                and isinstance(merged[key], dict)
                and isinstance(val, dict)
            ):
                merged[key] = self._deep_merge_dicts(merged[key], val)
            else:
                merged[key] = val
        return merged

    def _metadata_to_probed(self, meta: dict[str, Any]) -> dict[str, Any]:
        """
        Convert raw ffprobe JSON into the structured 'probed' shape our
        ingest/handler expects.

        We keep it small and predictable:
        {
            "duration_ms": ...,
            "bitrate": ...,
            "container": ...,
            "video": {
                "codec": ...,
                "width": ...,
                "height": ...,
                "fps": ...,
            },
            "audio": [
                {"codec": ..., "channels": ..., "sample_rate": ..., "language": ...},
                ...
            ],
        }
        """
        if not meta:
            return {}

        probed: dict[str, Any] = {}

        # format-level stuff
        fmt = meta.get("format") or {}
        if "duration" in fmt:
            try:
                dur_sec = float(fmt["duration"])
                probed["duration_ms"] = int(dur_sec * 1000)
            except Exception:
                pass

        if "bit_rate" in fmt:
            try:
                probed["bitrate"] = int(fmt["bit_rate"])
            except Exception:
                probed["bitrate"] = fmt["bit_rate"]

        if "format_name" in fmt:
            probed["container"] = fmt["format_name"]

        # streams
        streams = meta.get("streams") or []
        video_block: dict[str, Any] = {}
        audio_blocks: list[dict[str, Any]] = []

        for st in streams:
            codec_type = st.get("codec_type")
            if codec_type == "video" and not video_block:
                video_block["codec"] = st.get("codec_name")
                video_block["width"] = st.get("width")
                video_block["height"] = st.get("height")

                # fps can come as "r_frame_rate": "24000/1001"
                r_frame_rate = st.get("r_frame_rate") or st.get("avg_frame_rate")
                if r_frame_rate and r_frame_rate != "0/0":
                    try:
                        num, den = r_frame_rate.split("/")
                        fps = float(num) / float(den)
                        video_block["fps"] = fps
                    except Exception:
                        pass

                # sometimes bit_rate is on the stream
                if st.get("bit_rate"):
                    try:
                        video_block["bitrate"] = int(st["bit_rate"])
                    except Exception:
                        video_block["bitrate"] = st["bit_rate"]

            elif codec_type == "audio":
                ab: dict[str, Any] = {
                    "codec": st.get("codec_name"),
                    "channels": st.get("channels"),
                    "sample_rate": st.get("sample_rate"),
                }
                if st.get("tags") and st["tags"].get("language"):
                    ab["language"] = st["tags"]["language"]
                audio_blocks.append({k: v for k, v in ab.items() if v is not None})

        if video_block:
            # drop Nones
            probed["video"] = {k: v for k, v in video_block.items() if v is not None}
        if audio_blocks:
            probed["audio"] = audio_blocks

        return {k: v for k, v in probed.items() if v is not None}

    def _metadata_to_labels(self, metadata: dict[str, Any]) -> list[str]:
        """
        Convert metadata dictionary to label list.

        Args:
            metadata: Dictionary containing extracted metadata

        Returns:
            List of labels in "key:value" format
        """
        labels = []

        # Duration from format
        fmt = metadata.get("format") or {}
        if "duration" in fmt:
            try:
                duration_ms = int(float(fmt["duration"]) * 1000)
                labels.append(f"duration_ms:{duration_ms}")
            except Exception:
                pass

        # Container format
        if "format_name" in fmt:
            labels.append(f"container:{fmt['format_name']}")

        # Streams
        streams = metadata.get("streams") or []
        video_streams = [s for s in streams if s.get("codec_type") == "video"]
        audio_streams = [s for s in streams if s.get("codec_type") == "audio"]

        if video_streams:
            vs = video_streams[0]
            if vs.get("codec_name"):
                labels.append(f"video_codec:{vs['codec_name']}")
            if vs.get("width") and vs.get("height"):
                labels.append(f"resolution:{vs['width']}x{vs['height']}")

        if audio_streams:
            as_ = audio_streams[0]
            if as_.get("codec_name"):
                labels.append(f"audio_codec:{as_['codec_name']}")

        # Chapters count
        chapters = metadata.get("chapters") or []
        if isinstance(chapters, list) and chapters:
            labels.append(f"chapters:{len(chapters)}")

        return labels
