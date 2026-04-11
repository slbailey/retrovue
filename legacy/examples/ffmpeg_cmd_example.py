#!/usr/bin/env python3
"""
Example usage of the FFmpeg command builder module.

This script demonstrates how to use the retrovue.streaming.ffmpeg_cmd module to build
FFmpeg commands for MPEG-TS live streaming with concat demuxer.
"""

from retrovue.streaming.ffmpeg_cmd import build_cmd, get_cmd_summary, validate_cmd_args


def main():
    """Demonstrate FFmpeg command building."""
    print("FFmpeg Command Builder Example")
    print("=" * 40)
    
    # Example 1: Basic transcode command
    print("\n1. Basic Transcode Command:")
    transcode_cmd = build_cmd("/path/to/concat.txt", mode="transcode")
    print("Command:", " ".join(transcode_cmd))
    print("Summary:", get_cmd_summary(transcode_cmd))
    
    # Example 2: Copy mode command
    print("\n2. Copy Mode Command:")
    copy_cmd = build_cmd("/path/to/concat.txt", mode="copy")
    print("Command:", " ".join(copy_cmd))
    print("Summary:", get_cmd_summary(copy_cmd))
    
    # Example 3: Custom parameters
    print("\n3. Custom Parameters:")
    custom_cmd = build_cmd(
        "/path/to/concat.txt",
        mode="transcode",
        video_preset="fast",
        gop=120,
        audio_bitrate="256k",
        audio_rate=44100,
        stereo=False,
        probe_size="5M",
        analyze_duration="1M"
    )
    print("Command:", " ".join(custom_cmd))
    print("Summary:", get_cmd_summary(custom_cmd))
    
    # Example 4: Validation
    print("\n4. Command Validation:")
    validation = validate_cmd_args(transcode_cmd)
    print("Validation results:")
    for key, value in validation.items():
        print(f"  {key}: {value}")
    
    # Example 5: High-quality streaming
    print("\n5. High-Quality Streaming:")
    hq_cmd = build_cmd(
        "/path/to/concat.txt",
        mode="transcode",
        video_preset="medium",  # Higher quality
        gop=60,
        audio_bitrate="320k",   # Higher audio quality
        audio_rate=48000,
        stereo=True
    )
    print("Command:", " ".join(hq_cmd))
    print("Summary:", get_cmd_summary(hq_cmd))
    
    # Example 6: Low-latency streaming
    print("\n6. Low-Latency Streaming:")
    lowlat_cmd = build_cmd(
        "/path/to/concat.txt",
        mode="transcode",
        video_preset="ultrafast",  # Fastest encoding
        gop=30,                    # Smaller GOP for lower latency
        audio_bitrate="128k",
        audio_rate=48000,
        stereo=True
    )
    print("Command:", " ".join(lowlat_cmd))
    print("Summary:", get_cmd_summary(lowlat_cmd))


if __name__ == "__main__":
    main()
