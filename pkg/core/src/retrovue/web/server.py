"""
Web server for Retrovue IPTV streaming.

Provides FastAPI-based HTTP serving for MPEG-TS streams and IPTV playlists.
"""

from __future__ import annotations

import gzip
import io
import json
import logging
import os
import re
import subprocess
import tempfile

import uvicorn
from fastapi import FastAPI, Request, Response
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from starlette.middleware.base import BaseHTTPMiddleware

from retrovue.streaming.ffmpeg_cmd import build_cmd
from retrovue.streaming.mpegts_stream import MPEGTSStreamer

logger = logging.getLogger(__name__)

# Global storage for active streams - maps channel_id to asset info
_active_streams: dict[str, dict] = {}


class ConditionalGZipMiddleware(BaseHTTPMiddleware):
    """
    Custom GZip middleware that excludes .ts routes from compression.

    This middleware applies gzip compression to responses, but skips compression
    for routes that match the pattern /iptv/channel/.*\\.ts$ to ensure proper
    MPEG-TS streaming without compression artifacts.
    """

    def __init__(self, app, minimum_size: int = 1000):
        super().__init__(app)
        self.minimum_size = minimum_size
        # Compile regex patterns for excluded paths
        self.excluded_patterns = [
            re.compile(r"^/iptv/channel/.*\.ts$"),
        ]

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)

        # Check if this path should be excluded from compression
        if self._should_exclude_path(request.url.path):
            return response

        # Check if response should be compressed
        if not self._should_compress(request, response):
            return response

        # Apply gzip compression
        return await self._compress_response(response)

    def _should_exclude_path(self, path: str) -> bool:
        """Check if the path should be excluded from compression."""
        return any(pattern.match(path) for pattern in self.excluded_patterns)

    def _should_compress(self, request: Request, response: Response) -> bool:
        """Check if the response should be compressed."""
        # Check if client accepts gzip
        accept_encoding = request.headers.get("accept-encoding", "").lower()
        if "gzip" not in accept_encoding:
            return False

        # Check if response is large enough
        content_length = response.headers.get("content-length")
        if content_length and int(content_length) < self.minimum_size:
            return False

        # Don't compress if already compressed
        if response.headers.get("content-encoding"):
            return False

        return True

    async def _compress_response(self, response: Response) -> Response:
        """Apply gzip compression to the response."""
        # Get response body
        if hasattr(response, "body"):
            body = response.body
        else:
            # For streaming responses, we can't compress them
            return response

        # Compress the body
        gzip_buffer = io.BytesIO()
        with gzip.GzipFile(fileobj=gzip_buffer, mode="wb") as gzip_file:
            gzip_file.write(body)
        compressed_body = gzip_buffer.getvalue()

        # Create new response with compressed body
        new_response = Response(
            content=compressed_body,
            status_code=response.status_code,
            headers=dict(response.headers),
            media_type=response.media_type,
        )

        # Set compression headers
        new_response.headers["Content-Encoding"] = "gzip"
        new_response.headers["Content-Length"] = str(len(compressed_body))
        new_response.headers["Vary"] = "Accept-Encoding"

        return new_response


def resolve_asset_by_channel_id(channel_id: str, active_streams: dict | None = None) -> dict:
    """
    Resolve an asset by channel ID.

    Args:
        channel_id: Channel identifier
        active_streams: Dictionary of active streams

    Returns:
        Dict with asset information: {"path": str}
    """
    # Use passed-in streams or global fallback
    streams = active_streams or _active_streams

    # Check if we have an active stream for this channel
    if channel_id in streams:
        logger.info(f"Found active stream for channel {channel_id}: {streams[channel_id]}")
        return streams[channel_id]

    # Fallback to a default asset if no active stream
    logger.warning(f"No active stream found for channel {channel_id}, using fallback")
    return {
        "path": "R:\\Media\\TV\\Cheers (1982) {imdb-tt0083399}\\Season 01\\Cheers (1982) - S01E03 - The Tortelli Tort [Bluray-720p][AAC 2.0][x264]-Bordure.mp4"
    }


def set_active_stream(channel_id: str, asset_info: dict) -> None:
    """
    Set the active stream asset for a channel.

    Args:
        channel_id: Channel identifier
        asset_info: Asset information dict with 'path' key
    """
    logger.info(f"Setting active stream for channel {channel_id}: {asset_info}")
    _active_streams[channel_id] = asset_info


def analyze_ts_cadence(data: bytes) -> dict:
    """
    Analyze MPEG-TS packet cadence by looking for 0x47 sync bytes.

    Args:
        data: Raw MPEG-TS data bytes

    Returns:
        Dict with cadence analysis results
    """
    sync_byte = 0x47
    packet_size = 188
    max_packets = 10

    # Find all 0x47 sync bytes
    sync_positions = []
    for i, byte in enumerate(data):
        if byte == sync_byte:
            sync_positions.append(i)
            if len(sync_positions) >= max_packets:
                break

    if len(sync_positions) < 2:
        return {
            "valid": False,
            "reason": "Insufficient sync bytes found",
            "sync_count": len(sync_positions),
        }

    # Check if positions are at 188-byte intervals
    intervals = []
    for i in range(1, len(sync_positions)):
        interval = sync_positions[i] - sync_positions[i - 1]
        intervals.append(interval)

    # Check if all intervals are 188 bytes
    valid_intervals = all(interval == packet_size for interval in intervals)

    return {
        "valid": valid_intervals,
        "sync_count": len(sync_positions),
        "intervals": intervals,
        "expected_interval": packet_size,
        "first_sync_position": sync_positions[0] if sync_positions else None,
    }


def extract_codec_summary(probe_data: dict) -> dict:
    """
    Extract codec summary from ffprobe JSON output.

    Args:
        probe_data: Parsed JSON from ffprobe

    Returns:
        Dict with codec summary
    """
    streams = probe_data.get("streams", [])

    video_streams = []
    audio_streams = []

    for stream in streams:
        codec_type = stream.get("codec_type", "")
        codec_name = stream.get("codec_name", "unknown")

        if codec_type == "video":
            video_streams.append(
                {
                    "codec": codec_name,
                    "width": stream.get("width"),
                    "height": stream.get("height"),
                    "bit_rate": stream.get("bit_rate"),
                }
            )
        elif codec_type == "audio":
            audio_streams.append(
                {
                    "codec": codec_name,
                    "sample_rate": stream.get("sample_rate"),
                    "channels": stream.get("channels"),
                    "bit_rate": stream.get("bit_rate"),
                }
            )

    return {
        "video_streams": video_streams,
        "audio_streams": audio_streams,
        "total_streams": len(streams),
    }


def run_server(port: int = 8000, active_streams: dict | None = None, debug: bool = False):
    app = FastAPI(title="Retrovue IPTV Server")

    # Add custom GZip middleware with exclusion for .ts routes
    app.add_middleware(ConditionalGZipMiddleware, minimum_size=1000)

    @app.middleware("http")
    async def streaming_headers(request: Request, call_next):
        resp: Response = await call_next(request)
        # Set appropriate headers for streaming content
        if request.url.path.endswith(".ts"):
            # MPEG-TS streams should not be cached
            resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            resp.headers["Pragma"] = "no-cache"
            resp.headers["Expires"] = "0"
            resp.headers["Content-Type"] = "video/mp2t"
            # Ensure no compression for .ts files
            resp.headers["Content-Encoding"] = "identity"
        elif request.url.path.endswith(".m3u"):
            # IPTV playlists should not be cached
            resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            resp.headers["Pragma"] = "no-cache"
            resp.headers["Expires"] = "0"
            resp.headers["Content-Type"] = "application/vnd.apple.mpegurl"
        return resp

    # Set up Jinja2 templates
    templates = Jinja2Templates(directory="templates")

    @app.get("/debug/ts/{channel_id}")
    async def debug_ts_stream(channel_id: str):
        """
        Debug endpoint to analyze MPEG-TS stream data.

        Returns JSON with:
        - First 16 bytes as hex
        - 0x47 cadence analysis for first ~10 packets
        - FFprobe codec summary
        """
        try:
            # Resolve asset for this channel
            asset = resolve_asset_by_channel_id(channel_id, active_streams)
            source_path = asset["path"]

            # Create a temporary file to capture the first 4096 bytes
            with tempfile.NamedTemporaryFile(delete=False, suffix=".ts") as temp_file:
                temp_path = temp_file.name

            try:
                # Run FFmpeg to capture first 1 second of stream (copy mode for speed)
                cmd = [
                    "ffmpeg",
                    "-y",
                    "-t",
                    "1",
                    "-c",
                    "copy",
                    "-f",
                    "concat",
                    "-i",
                    source_path,
                    "-f",
                    "mpegts",
                    temp_path,
                ]

                # Execute FFmpeg command
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)

                if result.returncode != 0:
                    return {"error": f"FFmpeg failed: {result.stderr}", "channel_id": channel_id}

                # Read the first 4096 bytes
                with open(temp_path, "rb") as f:
                    data = f.read(4096)

                if len(data) < 16:
                    return {"error": "Insufficient data captured", "channel_id": channel_id}

                # Extract first 16 bytes as hex
                first_16_hex = data[:16].hex().upper()

                # Analyze 0x47 cadence for first ~10 packets
                cadence_analysis = analyze_ts_cadence(data)

                # Run ffprobe to get codec info
                probe_cmd = [
                    "ffprobe",
                    "-v",
                    "quiet",
                    "-print_format",
                    "json",
                    "-show_streams",
                    temp_path,
                ]

                probe_result = subprocess.run(probe_cmd, capture_output=True, text=True, timeout=5)

                codec_info = {}
                if probe_result.returncode == 0:
                    try:
                        probe_data = json.loads(probe_result.stdout)
                        codec_info = extract_codec_summary(probe_data)
                    except json.JSONDecodeError:
                        codec_info = {"error": "Failed to parse ffprobe output"}
                else:
                    codec_info = {"error": f"FFprobe failed: {probe_result.stderr}"}

                return {
                    "channel_id": channel_id,
                    "first_16_bytes_hex": first_16_hex,
                    "cadence_analysis": cadence_analysis,
                    "codec_info": codec_info,
                    "data_length": len(data),
                }

            finally:
                # Clean up temporary file
                if os.path.exists(temp_path):
                    os.unlink(temp_path)

        except subprocess.TimeoutExpired:
            return {
                "error": "FFmpeg timeout - stream may not be accessible",
                "channel_id": channel_id,
            }
        except Exception as e:
            logger.error(f"Error in debug_ts_stream: {e}")
            return {"error": f"Debug analysis failed: {str(e)}", "channel_id": channel_id}

    @app.get("/debug/ts/ui", response_class=HTMLResponse)
    async def debug_ts_ui(request: Request):
        """
        Debug UI page that calls the JSON endpoint and displays results with badges.
        """
        return templates.TemplateResponse(
            "debug_ts.html", {"request": request, "title": "MPEG-TS Stream Debug"}
        )

    @app.get("/iptv/channel/{channel_id}.ts")
    async def stream_channel(channel_id: str, request: Request):
        """
        Streams a continuous MPEG-TS feed for the requested channel.
        """
        try:
            print(f"DEBUG: stream_channel called for channel {channel_id}")
            # Resolve asset for this channel
            asset = resolve_asset_by_channel_id(channel_id, active_streams)
            source_path = asset["path"]
            print(f"DEBUG: Resolved asset path: {source_path}")

            # Create concat file for the asset
            import tempfile

            concat_content = f"file '{source_path}'\n"
            with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
                f.write(concat_content)
                concat_path = f.name

            # Build FFmpeg command
            cmd = build_cmd(concat_path, mode="transcode", debug=debug)
            logger.info(f"Created FFmpeg command for channel {channel_id}")

            # Create async streamer
            streamer = MPEGTSStreamer(cmd)
            print("DEBUG: Created async streamer, starting stream")

            # Return streaming response with proper headers
            return StreamingResponse(
                streamer.stream(),
                media_type="video/mp2t",
                headers={
                    "Cache-Control": "no-cache, no-store, must-revalidate",
                    "Pragma": "no-cache",
                    "Expires": "0",
                    "Content-Encoding": "identity",
                },
            )

        except Exception as e:
            print(f"DEBUG: Exception in stream_channel: {e}")
            logger.error(f"Error streaming channel {channel_id}: {e}")
            return {"error": f"Failed to stream channel {channel_id}: {str(e)}"}

    @app.get("/iptv/channels.m3u")
    async def get_channels_playlist():
        """
        Serve IPTV channels playlist.
        TODO: Implement M3U playlist generation
        """
        # TODO: Generate M3U playlist from active channels
        return {"message": "M3U playlist endpoint - TODO"}

    @app.get("/iptv/guide.xml")
    async def get_guide():
        """
        Serve XMLTV guide.
        TODO: Implement XMLTV guide generation
        """
        # TODO: Generate XMLTV guide from channel schedule
        return {"message": "XMLTV guide endpoint - TODO"}

    @app.get("/")
    async def root():
        return {"message": "Retrovue IPTV Server", "status": "ready"}

    uvicorn.run(app, host="0.0.0.0", port=port)
