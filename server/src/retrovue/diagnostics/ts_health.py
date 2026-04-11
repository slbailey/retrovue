"""
Transport Stream (TS) health diagnostics for Retrovue.

This module provides utilities to analyze MPEG-TS streams for sync issues,
codec information, and overall health.
"""

import asyncio
import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any


async def capture_seconds(url: str, seconds: int, out: Path) -> None:
    """
    Capture a sample of the TS stream for the specified duration.

    Args:
        url: The URL of the TS stream to capture
        seconds: Duration in seconds to capture
        out: Output file path for the captured sample

    Raises:
        subprocess.CalledProcessError: If FFmpeg fails to capture the stream
    """
    cmd = [
        "ffmpeg",
        "-i",
        url,
        "-t",
        str(seconds),
        "-c",
        "copy",
        "-f",
        "mpegts",
        "-y",  # Overwrite output file
        str(out),
    ]

    process = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )

    stdout, stderr = await process.communicate()

    if process.returncode != 0:
        raise subprocess.CalledProcessError(
            process.returncode,
            cmd,
            stdout.decode() if stdout else "",
            stderr.decode() if stderr else "",
        )


def has_ts_sync(file: Path, sample_packets: int = 50) -> bool:
    """
    Check if the TS file has proper sync bytes at the expected positions.

    TS packets are 188 bytes long and should start with sync byte 0x47.

    Args:
        file: Path to the TS file to check
        sample_packets: Number of packets to check for sync

    Returns:
        True if sync bytes are found at expected positions, False otherwise
    """
    try:
        with open(file, "rb") as f:
            for i in range(sample_packets):
                # Each TS packet is 188 bytes, sync byte should be at position 0x47
                expected_pos = i * 188
                f.seek(expected_pos)
                byte = f.read(1)

                if not byte or byte[0] != 0x47:
                    return False

        return True
    except OSError:
        return False


def ffprobe_streams(file: Path) -> dict[str, Any]:
    """
    Analyze the TS file using ffprobe to extract stream information.

    Args:
        file: Path to the TS file to analyze

    Returns:
        Dictionary containing parsed stream information

    Raises:
        subprocess.CalledProcessError: If ffprobe fails
        json.JSONDecodeError: If ffprobe output cannot be parsed
    """
    cmd = ["ffprobe", "-show_streams", "-v", "error", "-of", "json", str(file)]

    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


def analyze_ts_health(file: Path) -> dict[str, Any]:
    """
    Perform comprehensive health analysis on a TS file.

    Args:
        file: Path to the TS file to analyze

    Returns:
        Dictionary containing health analysis results
    """
    results = {
        "file": str(file),
        "sync_check": False,
        "streams": {},
        "codecs": {"video": [], "audio": []},
        "errors": [],
    }

    try:
        # Check TS sync
        results["sync_check"] = has_ts_sync(file)

        # Get stream information
        probe_data = ffprobe_streams(file)
        results["streams"] = probe_data.get("streams", [])

        # Extract codec information
        for stream in results["streams"]:
            codec_name = stream.get("codec_name", "unknown")
            codec_type = stream.get("codec_type", "unknown")

            if codec_type == "video":
                results["codecs"]["video"].append(codec_name)
            elif codec_type == "audio":
                results["codecs"]["audio"].append(codec_name)

    except subprocess.CalledProcessError as e:
        results["errors"].append(f"FFprobe failed: {e.stderr}")
    except json.JSONDecodeError as e:
        results["errors"].append(f"Failed to parse ffprobe output: {e}")
    except Exception as e:
        results["errors"].append(f"Unexpected error: {e}")

    return results


async def diagnose_url(url: str, sample_duration: int = 5) -> dict[str, Any]:
    """
    Diagnose a TS stream URL by capturing a sample and analyzing it.

    Args:
        url: URL of the TS stream to diagnose
        sample_duration: Duration in seconds to capture for analysis

    Returns:
        Dictionary containing diagnosis results
    """
    with tempfile.NamedTemporaryFile(suffix=".ts", delete=False) as temp_file:
        temp_path = Path(temp_file.name)

    try:
        # Capture sample
        await capture_seconds(url, sample_duration, temp_path)

        # Analyze the captured sample
        results = analyze_ts_health(temp_path)
        results["url"] = url
        results["sample_duration"] = sample_duration

        return results

    finally:
        # Clean up temporary file
        if temp_path.exists():
            temp_path.unlink()


def print_diagnosis(results: dict[str, Any]) -> None:
    """
    Print formatted diagnosis results to console.

    Args:
        results: Diagnosis results from analyze_ts_health or diagnose_url
    """
    print("TS Health Diagnosis")
    print("==================")

    if "url" in results:
        print(f"URL: {results['url']}")
        print(f"Sample Duration: {results['sample_duration']}s")
    else:
        print(f"File: {results['file']}")

    print()

    # Sync check
    sync_status = "OK" if results["sync_check"] else "FAIL"
    print(f"TS Sync: {sync_status}")

    # Codec information
    video_codecs = results["codecs"]["video"]
    audio_codecs = results["codecs"]["audio"]

    if video_codecs:
        print(f"Video Codecs: {', '.join(set(video_codecs))}")
    else:
        print("Video Codecs: None detected")

    if audio_codecs:
        print(f"Audio Codecs: {', '.join(set(audio_codecs))}")
    else:
        print("Audio Codecs: None detected")

    # Errors
    if results["errors"]:
        print("\nErrors:")
        for error in results["errors"]:
            print(f"  - {error}")


async def main():
    """CLI entry point for TS health diagnostics."""
    import sys

    if len(sys.argv) != 2:
        print("Usage: python -m retrovue.diagnostics.ts_health <url>")
        sys.exit(1)

    url = sys.argv[1]

    try:
        results = await diagnose_url(url)
        print_diagnosis(results)

        # Exit with error code if sync check failed
        if not results["sync_check"]:
            sys.exit(1)

    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
