"""
FFmpeg MPEG-TS renderer for streaming output.

This renderer consumes producer input URLs and outputs MPEG-TS streams using FFmpeg.
It handles FFmpeg process lifecycle, encoding, and stream endpoint management.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
import subprocess
from typing import Any

from retrovue.streaming.ffmpeg_cmd import build_cmd
from retrovue.streaming.mpegts_stream import MPEGTSStreamer

from .base import (
    BaseRenderer,
    RendererConfig,
    RendererConfigurationError,
    RendererStartupError,
    UpdateFieldSpec,
)

logger = logging.getLogger(__name__)


class FFmpegTSRenderer(BaseRenderer):
    """
    FFmpeg-based MPEG-TS renderer.

    This renderer takes an input URL from a producer and outputs an MPEG-TS stream
    using FFmpeg. It supports both transcoding and copy modes for different
    performance requirements.

    The renderer outputs to stdout (pipe:1) which can be consumed by HTTP servers
    or other stream consumers.
    """

    name = "ffmpeg-ts"

    def __init__(
        self,
        mode: str = "transcode",
        video_preset: str = "veryfast",
        gop: int = 60,
        audio_bitrate: str = "128k",
        audio_rate: int = 48000,
        stereo: bool = True,
        probe_size: str = "10M",
        analyze_duration: str = "2M",
        audio_optional: bool = True,
        audio_required: bool = False,
        debug: bool = False,
        output_url: str = "tcp://127.0.0.1:1234?listen",
        **config: Any,
    ) -> None:
        """
        Initialize the FFmpeg TS renderer.

        Args:
            mode: Streaming mode - "transcode" for re-encoding or "copy" for passthrough
            video_preset: x264 preset for transcoding
            gop: Group of Pictures size for video encoding
            audio_bitrate: Audio bitrate (e.g., "128k", "256k")
            audio_rate: Audio sample rate in Hz
            stereo: Whether to force stereo audio output
            probe_size: Maximum size to probe for stream information
            analyze_duration: Maximum duration to analyze for stream information
            audio_optional: If True (default), use optional audio stream
            audio_required: If True, use required audio stream
            debug: If True, use verbose logging level for debugging
            output_url: Destination for the MPEG-TS stream (default: tcp://127.0.0.1:1234?listen).
                - "tcp://127.0.0.1:1234?listen": FFmpeg opens a TCP listener that clients (e.g. VLC) can connect to.
                - "pipe:1": stream to stdout for Python-managed delivery.
            **config: Additional configuration parameters
        """
        initial_config: dict[str, Any] = {
            "mode": mode,
            "video_preset": video_preset,
            "gop": gop,
            "audio_bitrate": audio_bitrate,
            "audio_rate": audio_rate,
            "stereo": stereo,
            "probe_size": probe_size,
            "analyze_duration": analyze_duration,
            "audio_optional": audio_optional,
            "audio_required": audio_required,
            "debug": debug,
            "output_url": output_url,
        }
        initial_config.update(config)

        super().__init__(**initial_config)

        # Cache validated configuration on the instance for convenience
        self.mode = self.config["mode"]
        self.video_preset = self.config["video_preset"]
        self.gop = self.config["gop"]
        self.audio_bitrate = self.config["audio_bitrate"]
        self.audio_rate = self.config["audio_rate"]
        self.stereo = self.config["stereo"]
        self.probe_size = self.config["probe_size"]
        self.analyze_duration = self.config["analyze_duration"]
        self.audio_optional = self.config["audio_optional"]
        self.audio_required = self.config["audio_required"]
        self.debug = self.config["debug"]
        self.output_url = self.config["output_url"]

        # Runtime state
        self._streamer: MPEGTSStreamer | None = None
        self._input_url: str | None = None
        self._concat_path: str | None = None
        self._stream_endpoint: str | None = None
        self._stream_task: asyncio.Task | None = None
        self._running = False
        self._process: subprocess.Popen | None = None

    def start(self, input_url: str | None = None, context: dict[str, Any] | None = None) -> str:
        """
        Start rendering the input source and return a stream endpoint.

        This method creates a concat file from the input URL (for FFmpeg compatibility)
        and prepares the FFmpeg process to output MPEG-TS stream.

        Args:
            input_url: FFmpeg-compatible input source (from producer.get_input_url())
            context: Optional context dictionary (currently unused)

        Returns:
            Stream endpoint identifier ("pipe:1" for stdout-based streaming)

        Raises:
            RendererStartupError: If rendering cannot be started

        Note:
            The actual FFmpeg process execution is async and should be managed by
            ChannelManager or similar component using the MPEGTSStreamer instance
            returned by get_streamer().
        """
        if input_url is None:
            input_url = self._last_input_url

        if input_url is None:
            raise RendererStartupError(
                "No input URL provided. Call start with an input_url or switch_source first."
            )

        if self._running:
            logger.info("Restarting renderer with new source")
            self.stop()

        try:
            is_lavfi_input = input_url.startswith("lavfi:")

            self._input_url = input_url
            self._last_input_url = input_url
            output_url = self.output_url

            if is_lavfi_input:
                self._concat_path = None
                cmd = self._build_direct_input_cmd(
                    input_url=input_url,
                    mode=self.mode,
                    video_preset=self.video_preset,
                    gop=self.gop,
                    audio_bitrate=self.audio_bitrate,
                    audio_rate=self.audio_rate,
                    stereo=self.stereo,
                    audio_optional=self.audio_optional,
                    audio_required=self.audio_required,
                    debug=self.debug,
                    output_url=output_url,
                )
                validate_inputs = False
            else:
                concat_path = self._create_concat_file(input_url)
                self._concat_path = concat_path
                cmd = build_cmd(
                    concat_path=concat_path,
                    mode=self.mode,
                    video_preset=self.video_preset,
                    gop=self.gop,
                    audio_bitrate=self.audio_bitrate,
                    audio_rate=self.audio_rate,
                    stereo=self.stereo,
                    probe_size=self.probe_size,
                    analyze_duration=self.analyze_duration,
                    audio_optional=self.audio_optional,
                    audio_required=self.audio_required,
                    debug=self.debug,
                )
                cmd[-1] = output_url
                validate_inputs = True

            if output_url == "pipe:1":
                # Create streamer instance (used by ChannelManager for async streaming)
                self._streamer = MPEGTSStreamer(cmd=cmd, validate_inputs=validate_inputs)
                self._process = None
            else:
                # Launch FFmpeg process directly; it handles network/file output.
                # No streamer is needed in this mode.
                self._process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                self._streamer = None

            # Mark as running and return the endpoint
            self._running = True
            self._stream_endpoint = output_url

            logger.info(f"FFmpeg TS renderer started with input: {input_url}")
            logger.info(f"FFmpeg command prepared: {' '.join(cmd)}")
            return self._stream_endpoint

        except Exception as e:
            logger.error(f"Failed to start FFmpeg TS renderer: {e}")
            # Clean up concat file if it was created
            if hasattr(self, "_concat_path") and self._concat_path:
                try:
                    Path(self._concat_path).unlink()
                except Exception:
                    pass
            raise RendererStartupError(f"Failed to start renderer: {e}") from e

    def stop(self) -> bool:
        """
        Stop the rendering process and clean up resources.

        Returns:
            True if rendering stopped successfully, False otherwise
        """
        if not self._running:
            logger.warning("Renderer is not running")
            return True

        try:
            self._running = False

            # Clean up streamer if it exists
            if self._streamer:
                # The MPEGTSStreamer has its own cleanup logic
                # We'd need to call its cleanup method or cancel the stream
                self._streamer = None
            if self._process:
                try:
                    self._process.terminate()
                    self._process.wait(timeout=5)
                except Exception as exc:
                    logger.warning(f"Failed to terminate FFmpeg process: {exc}")
                finally:
                    self._process = None

            # Clean up concat file if it was created
            if self._concat_path and Path(self._concat_path).exists():
                try:
                    Path(self._concat_path).unlink()
                    logger.debug(f"Cleaned up concat file: {self._concat_path}")
                except Exception as e:
                    logger.warning(f"Failed to clean up concat file: {e}")

            self._stream_endpoint = None
            self._input_url = None
            self._concat_path = None

            logger.info("FFmpeg TS renderer stopped")
            return True

        except Exception as e:
            logger.error(f"Error stopping FFmpeg TS renderer: {e}")
            return False

    def get_stream_endpoint(self) -> str | None:
        """
        Get the current stream endpoint.

        Returns:
            Stream endpoint identifier, or None if not available
        """
        return self._stream_endpoint if self._running else None

    def is_running(self) -> bool:
        """
        Check if the renderer is currently running.

        Returns:
            True if renderer is running, False otherwise
        """
        return self._running

    def _create_concat_file(self, input_url: str) -> str:
        """
        Create a concat file for FFmpeg input.

        Args:
            input_url: Input URL (file path or lavfi specifier)

        Returns:
            Path to the created concat file
        """
        import tempfile

        # Create a temporary concat file
        concat_file = tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False)
        concat_path = concat_file.name

        try:
            # Write concat file format
            # For single inputs, we just write the file path
            # For lavfi inputs, we wrap them appropriately
            if input_url.startswith("lavfi:"):
                # Lavfi inputs need special handling - we can pass them directly
                # But concat format is: file 'input'
                concat_file.write(f"file '{input_url}'\n")
            else:
                # Regular file path
                concat_file.write(f"file '{input_url}'\n")

            concat_file.close()
            return concat_path

        except Exception as e:
            concat_file.close()
            try:
                Path(concat_path).unlink()
            except Exception:
                pass
            raise RendererStartupError(f"Failed to create concat file: {e}") from e

    def _build_direct_input_cmd(
        self,
        input_url: str,
        mode: str,
        video_preset: str,
        gop: int,
        audio_bitrate: str,
        audio_rate: int,
        stereo: bool,
        audio_optional: bool,
        audio_required: bool,
        debug: bool,
        output_url: str,
    ) -> list[str]:
        """
        Build an FFmpeg command for direct input (e.g., lavfi test patterns).

        Args:
            input_url: FFmpeg-compatible input (e.g., lavfi source)
            mode: Streaming mode ("transcode" or "copy")
            video_preset: x264 preset for transcoding
            gop: Group of Pictures size
            audio_bitrate: Audio bitrate string
            audio_rate: Audio sample rate
            stereo: Whether to force stereo audio
            audio_optional: Whether audio is optional
            audio_required: Whether audio is required
            debug: Enable verbose logging
            output_url: Destination for MPEG-TS stream

        Returns:
            List representing the FFmpeg command to execute.
        """
        cmd = ["ffmpeg", "-re"]

        log_level = "debug" if debug else "error"
        cmd.extend(["-hide_banner", "-nostats", "-loglevel", log_level])

        # Parse possible combined lavfi specification (video=...|audio=...)
        if input_url.startswith("lavfi:"):
            input_spec = input_url[len("lavfi:") :]
        else:
            input_spec = input_url

        video_spec: str | None = None
        audio_spec: str | None = None

        if input_spec.startswith("video=") or input_spec.startswith("audio="):
            parts = input_spec.split("|")
            for part in parts:
                if part.startswith("video=") and video_spec is None:
                    video_spec = part[len("video=") :]
                elif part.startswith("audio=") and audio_spec is None:
                    audio_spec = part[len("audio=") :]
        else:
            video_spec = input_spec

        input_index = 0
        video_input_index = None
        audio_input_index = None

        if video_spec:
            cmd.extend(["-f", "lavfi", "-i", video_spec])
            video_input_index = input_index
            input_index += 1

        if audio_spec:
            cmd.extend(["-f", "lavfi", "-i", audio_spec])
            audio_input_index = input_index
            input_index += 1

        # When no explicit video spec was provided, treat the entire input as a generic source.
        if video_spec is None and audio_spec is None:
            cmd.extend(["-f", "lavfi", "-i", input_spec])
            video_input_index = 0

        if video_input_index is not None:
            cmd.extend(["-map", f"{video_input_index}:v:0"])

        if audio_input_index is not None:
            cmd.extend(["-map", f"{audio_input_index}:a:0"])

        cmd.extend(
            [
                "-c:v",
                "libx264",
                "-preset",
                video_preset,
                "-tune",
                "zerolatency",
            ]
        )

        if audio_input_index is not None:
            cmd.extend(
                [
                    "-c:a",
                    "aac",
                    "-b:a",
                    audio_bitrate,
                    "-ac",
                    "2",
                ]
            )

        cmd.extend(["-f", "mpegts", output_url])

        return cmd

    @classmethod
    def get_config_schema(cls) -> RendererConfig:
        """
        Return the configuration schema for FFmpeg TS renderer.

        Returns:
            RendererConfig with configuration parameters
        """
        return RendererConfig(
            required_params=[],
            optional_params=[
                {
                    "name": "mode",
                    "description": "Streaming mode: 'transcode' for re-encoding or 'copy' for passthrough",
                    "default": "transcode",
                },
                {
                    "name": "video_preset",
                    "description": "x264 preset for transcoding (ultrafast, superfast, veryfast, faster, fast, medium, slow, slower, veryslow)",
                    "default": "veryfast",
                },
                {
                    "name": "gop",
                    "description": "Group of Pictures size for video encoding",
                    "default": "60",
                },
                {
                    "name": "audio_bitrate",
                    "description": "Audio bitrate (e.g., '128k', '256k')",
                    "default": "128k",
                },
                {
                    "name": "audio_rate",
                    "description": "Audio sample rate in Hz",
                    "default": "48000",
                },
                {
                    "name": "stereo",
                    "description": "Whether to force stereo audio output",
                    "default": "true",
                },
                {
                    "name": "probe_size",
                    "description": "Maximum size to probe for stream information",
                    "default": "10M",
                },
                {
                    "name": "analyze_duration",
                    "description": "Maximum duration to analyze for stream information",
                    "default": "2M",
                },
                {
                    "name": "audio_optional",
                    "description": "If True, use optional audio stream (allows streams without audio)",
                    "default": "true",
                },
                {
                    "name": "audio_required",
                    "description": "If True, use required audio stream (overrides audio_optional)",
                    "default": "false",
                },
                {
                    "name": "debug",
                    "description": "If True, use verbose logging level for debugging",
                    "default": "false",
                },
                {
                    "name": "output_url",
                    "description": "Destination for MPEG-TS stream (e.g., 'pipe:1', 'tcp://127.0.0.1:1234?listen')",
                    "default": "tcp://127.0.0.1:1234?listen",
                },
            ],
            description="FFmpeg-based MPEG-TS renderer. Takes producer input and outputs MPEG-TS stream via FFmpeg.",
        )

    def _validate_parameter_types(self) -> None:
        """Validate configuration parameter types and values."""
        mode = self._safe_get_config("mode")
        if mode not in ("transcode", "copy"):
            raise RendererConfigurationError(f"mode must be 'transcode' or 'copy', got '{mode}'")

        video_preset = self._safe_get_config("video_preset")
        valid_presets = ("ultrafast", "superfast", "veryfast", "faster", "fast", "medium", "slow", "slower", "veryslow")
        if video_preset not in valid_presets:
            raise RendererConfigurationError(
                f"video_preset must be one of {valid_presets}, got '{video_preset}'"
            )

        gop = self._safe_get_config("gop")
        if not isinstance(gop, int) or gop <= 0:
            raise RendererConfigurationError("gop must be a positive integer")

        audio_rate = self._safe_get_config("audio_rate")
        if not isinstance(audio_rate, int) or audio_rate <= 0:
            raise RendererConfigurationError("audio_rate must be a positive integer")

        stereo = self._safe_get_config("stereo")
        if not isinstance(stereo, bool):
            raise RendererConfigurationError("stereo must be a boolean")

        audio_optional = self._safe_get_config("audio_optional")
        if not isinstance(audio_optional, bool):
            raise RendererConfigurationError("audio_optional must be a boolean")

        audio_required = self._safe_get_config("audio_required")
        if not isinstance(audio_required, bool):
            raise RendererConfigurationError("audio_required must be a boolean")

        debug = self._safe_get_config("debug")
        if not isinstance(debug, bool):
            raise RendererConfigurationError("debug must be a boolean")

        output_url = self._safe_get_config("output_url", "tcp://127.0.0.1:1234?listen")
        if not isinstance(output_url, str) or not output_url:
            raise RendererConfigurationError("output_url must be a non-empty string")

    @classmethod
    def get_update_fields(cls) -> list[UpdateFieldSpec]:
        """
        Return updatable fields for FFmpeg TS renderer.

        Returns:
            List of UpdateFieldSpec objects
        """
        return [
            UpdateFieldSpec(
                config_key="mode",
                cli_flag="--mode",
                help="Streaming mode: 'transcode' for re-encoding or 'copy' for passthrough",
                field_type="string",
                is_sensitive=False,
                is_immutable=False,
            ),
            UpdateFieldSpec(
                config_key="video_preset",
                cli_flag="--video-preset",
                help="x264 preset for transcoding",
                field_type="string",
                is_sensitive=False,
                is_immutable=False,
            ),
            UpdateFieldSpec(
                config_key="gop",
                cli_flag="--gop",
                help="Group of Pictures size for video encoding",
                field_type="int",
                is_sensitive=False,
                is_immutable=False,
            ),
            UpdateFieldSpec(
                config_key="audio_bitrate",
                cli_flag="--audio-bitrate",
                help="Audio bitrate (e.g., '128k', '256k')",
                field_type="string",
                is_sensitive=False,
                is_immutable=False,
            ),
            UpdateFieldSpec(
                config_key="audio_rate",
                cli_flag="--audio-rate",
                help="Audio sample rate in Hz",
                field_type="int",
                is_sensitive=False,
                is_immutable=False,
            ),
            UpdateFieldSpec(
                config_key="stereo",
                cli_flag="--stereo",
                help="Whether to force stereo audio output",
                field_type="bool",
                is_sensitive=False,
                is_immutable=False,
            ),
            UpdateFieldSpec(
                config_key="debug",
                cli_flag="--debug",
                help="If True, use verbose logging level for debugging",
                field_type="bool",
                is_sensitive=False,
                is_immutable=False,
            ),
            UpdateFieldSpec(
                config_key="output_url",
                cli_flag="--output-url",
                help="Destination for MPEG-TS stream (e.g., 'pipe:1', 'udp://host:port?pkt_size=1316')",
                field_type="string",
                is_sensitive=False,
                is_immutable=False,
            ),
        ]

    @classmethod
    def validate_partial_update(cls, partial_config: dict[str, Any]) -> None:
        """
        Validate partial configuration update for FFmpeg TS renderer.

        Args:
            partial_config: Dictionary containing fields to update

        Raises:
            RendererConfigurationError: If validation fails
        """
        if "mode" in partial_config:
            mode = partial_config["mode"]
            if mode not in ("transcode", "copy"):
                raise RendererConfigurationError(f"mode must be 'transcode' or 'copy', got '{mode}'")

        if "video_preset" in partial_config:
            preset = partial_config["video_preset"]
            valid_presets = (
                "ultrafast",
                "superfast",
                "veryfast",
                "faster",
                "fast",
                "medium",
                "slow",
                "slower",
                "veryslow",
            )
            if preset not in valid_presets:
                raise RendererConfigurationError(
                    f"video_preset must be one of {valid_presets}, got '{preset}'"
                )

        if "gop" in partial_config:
            gop = partial_config["gop"]
            if not isinstance(gop, int) or gop <= 0:
                raise RendererConfigurationError("gop must be a positive integer")

        if "audio_rate" in partial_config:
            rate = partial_config["audio_rate"]
            if not isinstance(rate, int) or rate <= 0:
                raise RendererConfigurationError("audio_rate must be a positive integer")

        if "stereo" in partial_config:
            if not isinstance(partial_config["stereo"], bool):
                raise RendererConfigurationError("stereo must be a boolean")

        if "audio_optional" in partial_config:
            if not isinstance(partial_config["audio_optional"], bool):
                raise RendererConfigurationError("audio_optional must be a boolean")

        if "audio_required" in partial_config:
            if not isinstance(partial_config["audio_required"], bool):
                raise RendererConfigurationError("audio_required must be a boolean")

        if "debug" in partial_config:
            if not isinstance(partial_config["debug"], bool):
                raise RendererConfigurationError("debug must be a boolean")

        if "output_url" in partial_config:
            output_url = partial_config["output_url"]
            if not isinstance(output_url, str) or not output_url:
                raise RendererConfigurationError("output_url must be a non-empty string")

    def _get_examples(self) -> list[str]:
        """Get example usage strings for FFmpeg TS renderer."""
        return [
            "retrovue renderer add --type ffmpeg-ts --name 'MPEG-TS Renderer'",
            "retrovue renderer add --type ffmpeg-ts --name 'Copy Mode Renderer' --mode copy",
            "retrovue renderer add --type ffmpeg-ts --name 'High Quality Renderer' --video-preset fast --audio-bitrate 256k",
        ]

    def get_streamer(self) -> MPEGTSStreamer | None:
        """
        Get the underlying MPEGTSStreamer instance.

        Returns:
            MPEGTSStreamer instance, or None if not started
        """
        return self._streamer

