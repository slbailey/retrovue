"""
FFmpeg Command Builder for MPEG-TS Live Streaming.

This module provides utilities for building FFmpeg commands optimized for
MPEG-TS live streaming using the concat demuxer, supporting both transcoding
and copy modes for different performance requirements.
"""

from __future__ import annotations

import pathlib
from typing import Literal


def validate_input_files(concat_path: str) -> dict[str, any]:
    """
    Validate input files for FFmpeg streaming.

    Args:
        concat_path: Path to the concat file

    Returns:
        Dictionary with validation results including:
        - valid: bool - Overall validation result
        - concat_exists: bool - Whether concat file exists
        - files_found: int - Number of files found in concat
        - files_missing: list[str] - List of missing files
        - files_invalid: list[str] - List of files that exist but are invalid
        - errors: list[str] - List of error messages
    """
    result = {
        "valid": True,
        "concat_exists": False,
        "files_found": 0,
        "files_missing": [],
        "files_invalid": [],
        "errors": [],
    }

    # Check if concat file exists
    concat_file = pathlib.Path(concat_path)
    if not concat_file.exists():
        result["valid"] = False
        result["errors"].append(f"Concat file does not exist: {concat_path}")
        return result

    result["concat_exists"] = True

    # Read and validate concat file contents
    try:
        with open(concat_file, encoding="utf-8") as f:
            lines = f.readlines()
    except Exception as e:
        result["valid"] = False
        result["errors"].append(f"Cannot read concat file: {e}")
        return result

    # Parse concat file and validate each file
    for line_num, line in enumerate(lines, 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue

        if line.startswith("file "):
            # Extract file path (remove quotes if present)
            file_path = line[5:].strip()
            if file_path.startswith("'") and file_path.endswith("'"):
                file_path = file_path[1:-1]
            elif file_path.startswith('"') and file_path.endswith('"'):
                file_path = file_path[1:-1]

            result["files_found"] += 1

            # Check if file exists
            file_obj = pathlib.Path(file_path)
            if not file_obj.exists():
                result["files_missing"].append(file_path)
                result["valid"] = False
                result["errors"].append(f"File not found (line {line_num}): {file_path}")
            else:
                # Check if file is readable and has content
                try:
                    if file_obj.stat().st_size == 0:
                        result["files_invalid"].append(file_path)
                        result["valid"] = False
                        result["errors"].append(f"File is empty (line {line_num}): {file_path}")
                except Exception as e:
                    result["files_invalid"].append(file_path)
                    result["valid"] = False
                    result["errors"].append(
                        f"Cannot access file (line {line_num}): {file_path} - {e}"
                    )
        else:
            result["errors"].append(f"Invalid line format (line {line_num}): {line}")

    if result["files_found"] == 0:
        result["valid"] = False
        result["errors"].append("No valid files found in concat file")

    return result


def build_cmd(
    concat_path: str,
    mode: Literal["transcode", "copy"] = "transcode",
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
) -> list[str]:
    """
    Build FFmpeg command for MPEG-TS live streaming using concat demuxer.

    Args:
        concat_path: Path to the concat file listing video files to stream
        mode: Streaming mode - "transcode" for re-encoding or "copy" for passthrough
        video_preset: x264 preset for transcoding (ultrafast, superfast, veryfast, faster, fast, medium, slow, slower, veryslow)
        gop: Group of Pictures size for video encoding
        audio_bitrate: Audio bitrate (e.g., "128k", "256k")
        audio_rate: Audio sample rate in Hz
        stereo: Whether to force stereo audio output
        probe_size: Maximum size to probe for stream information
        analyze_duration: Maximum duration to analyze for stream information
        audio_optional: If True (default), use -map 0:a:0? (optional audio stream)
        audio_required: If True, use -map 0:a:0 (required audio stream). Overrides audio_optional
        debug: If True, use verbose logging level for debugging

    Returns:
        List of FFmpeg command arguments

    Audio Mapping Behavior:
        - audio_optional=True (default): Uses -map 0:a:0? which allows streams without audio
        - audio_required=True: Uses -map 0:a:0 which requires audio stream to be present
        - If both are True, audio_required takes precedence

    Example:
        >>> cmd = build_cmd("/path/to/concat.txt", mode="transcode")
        >>> # Returns: ["ffmpeg", "-nostdin", "-hide_banner", ...]
    """
    cmd = ["ffmpeg"]

    # Global flags
    log_level = "debug" if debug else "error"
    cmd.extend(
        [
            "-nostdin",
            "-hide_banner",
            "-nostats",
            "-loglevel",
            log_level,
            "-fflags",
            "+genpts+discardcorrupt+igndts",
            "-re",
        ]
    )

    # Concat input
    cmd.extend(
        [
            "-f",
            "concat",
            "-safe",
            "0",
            "-protocol_whitelist",
            "file,http,https,tcp,tls",
            "-probesize",
            probe_size,
            "-analyzeduration",
            analyze_duration,
            "-i",
            concat_path,
        ]
    )

    # Mapping
    cmd.extend(["-map", "0:v:0", "-sn", "-dn"])

    # Audio mapping based on parameters
    if audio_required:
        cmd.extend(["-map", "0:a:0"])
    elif audio_optional:
        cmd.extend(["-map", "0:a:0?"])

    if mode == "transcode":
        # Video encoding
        cmd.extend(
            [
                "-c:v",
                "libx264",
                "-preset",
                video_preset,
                "-tune",
                "zerolatency",
                "-profile:v",
                "main",
                "-pix_fmt",
                "yuv420p",
                "-g",
                str(gop),
                "-keyint_min",
                str(gop),
                "-sc_threshold",
                "0",
                "-bf",
                "0",
                "-flags",
                "cgop",
            ]
        )

        # Audio encoding
        audio_channels = "2" if stereo else "1"
        cmd.extend(
            ["-c:a", "aac", "-b:a", audio_bitrate, "-ac", audio_channels, "-ar", str(audio_rate)]
        )

    elif mode == "copy":
        # Video copy with bitstream filter
        cmd.extend(["-c:v", "copy", "-bsf:v", "h264_mp4toannexb"])

        # Audio copy (allow future AAC override if needed)
        cmd.extend(["-c:a", "copy"])

    # TS muxing
    cmd.extend(
        [
            "-muxpreload",
            "0",
            "-muxdelay",
            "0",
            "-f",
            "mpegts",
            "-mpegts_flags",
            "+initial_discontinuity+resend_headers",
            "pipe:1",
        ]
    )

    return cmd


def validate_cmd_args(cmd: list[str]) -> dict[str, bool]:
    """
    Validate FFmpeg command arguments for MPEG-TS streaming.

    Args:
        cmd: List of FFmpeg command arguments

    Returns:
        Dictionary with validation results

    Example:
        >>> cmd = build_cmd("/path/to/concat.txt")
        >>> results = validate_cmd_args(cmd)
        >>> assert results["has_global_flags"]
        >>> assert results["has_concat_input"]
        >>> assert not results["has_mp4_flags"]
    """
    cmd_str = " ".join(cmd)

    return {
        "has_global_flags": all(
            flag in cmd_str for flag in ["-nostdin", "-hide_banner", "-nostats", "-loglevel error"]
        ),
        "has_concat_input": "-f concat" in cmd_str and "-safe 0" in cmd_str,
        "has_protocol_whitelist": "-protocol_whitelist" in cmd_str,
        "has_mapping": "-map 0:v:0" in cmd_str
        and ("-map 0:a:0?" in cmd_str or "-map 0:a:0" in cmd_str),
        "has_ts_mux": "-f mpegts" in cmd_str and "-mpegts_flags" in cmd_str,
        "has_initial_discontinuity": "+initial_discontinuity" in cmd_str,
        "has_resend_headers": "+resend_headers" in cmd_str,
        "outputs_to_stdout": cmd_str.endswith("pipe:1"),
        "has_mp4_flags": "-movflags" in cmd_str or "+faststart" in cmd_str,
        "has_transcode_video": "-c:v libx264" in cmd_str,
        "has_copy_video": "-c:v copy" in cmd_str,
        "has_bsf_filter": "-bsf:v h264_mp4toannexb" in cmd_str,
        "has_audio_encoding": "-c:a aac" in cmd_str,
        "has_audio_copy": "-c:a copy" in cmd_str,
        "has_optional_audio": "-map 0:a:0?" in cmd_str,
        "has_required_audio": "-map 0:a:0" in cmd_str and "-map 0:a:0?" not in cmd_str,
    }


def get_cmd_summary(cmd: list[str]) -> str:
    """
    Get a human-readable summary of the FFmpeg command.

    Args:
        cmd: List of FFmpeg command arguments

    Returns:
        Formatted string summary of the command
    """
    if not cmd or cmd[0] != "ffmpeg":
        return "Invalid FFmpeg command"

    # Extract key components
    input_file = None
    mode = "unknown"
    video_codec = "unknown"
    audio_codec = "unknown"

    for i, arg in enumerate(cmd):
        if arg == "-i" and i + 1 < len(cmd):
            input_file = cmd[i + 1]
        elif arg == "-c:v":
            video_codec = cmd[i + 1] if i + 1 < len(cmd) else "unknown"
        elif arg == "-c:a":
            audio_codec = cmd[i + 1] if i + 1 < len(cmd) else "unknown"

    if video_codec == "libx264":
        mode = "transcode"
    elif video_codec == "copy":
        mode = "copy"

    return f"FFmpeg {mode} command: {video_codec} video, {audio_codec} audio, input: {input_file}"


# Test data for validation
TEST_CONCAT_PATH = "/tmp/test_concat.txt"
TEST_COMMANDS = {
    "transcode": build_cmd(TEST_CONCAT_PATH, mode="transcode"),
    "copy": build_cmd(TEST_CONCAT_PATH, mode="copy"),
    "transcode_custom": build_cmd(
        TEST_CONCAT_PATH,
        mode="transcode",
        video_preset="fast",
        gop=120,
        audio_bitrate="256k",
        stereo=False,
    ),
    "audio_optional": build_cmd(TEST_CONCAT_PATH, audio_optional=True, audio_required=False),
    "audio_required": build_cmd(TEST_CONCAT_PATH, audio_optional=False, audio_required=True),
}
