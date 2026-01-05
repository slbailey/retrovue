"""
Low latency streaming presets for Retrovue.

This module provides helper functions to apply low latency settings
for video and audio transcoding, optimized for real-time streaming.
"""


def apply_low_latency_video(args: list[str], gop: int) -> list[str]:
    """
    Apply low latency video settings to FFmpeg arguments.

    For transcode mode, sets:
    - -tune zerolatency
    - -bf 0 (no B-frames)
    - -flags cgop (closed GOP)
    - -g/gop_size to the given GOP value
    - -keyint_min to the given GOP value
    - -sc_threshold 0 (no scene change detection)

    Args:
        args: List of existing FFmpeg arguments
        gop: GOP (Group of Pictures) size for keyframe interval

    Returns:
        Updated list of FFmpeg arguments with low latency video settings
    """
    # Create a copy to avoid modifying the original list
    result_args = args.copy()

    # Low latency video settings
    low_latency_video_flags = [
        "-tune",
        "zerolatency",
        "-bf",
        "0",  # No B-frames
        "-flags",
        "cgop",  # Closed GOP
        "-g",
        str(gop),  # GOP size
        "-keyint_min",
        str(gop),  # Minimum keyframe interval
        "-sc_threshold",
        "0",  # No scene change detection
    ]

    # Insert the low latency flags after the input specification
    # Find the last input file index to insert after it
    input_index = -1
    for i, arg in enumerate(result_args):
        if not arg.startswith("-") and not arg.startswith("[") and not arg.startswith("]"):
            # This is likely an input file
            input_index = i

    # Insert after the last input file, or at the beginning if no input found
    insert_index = input_index + 1 if input_index >= 0 else 0
    result_args[insert_index:insert_index] = low_latency_video_flags

    return result_args


def apply_low_latency_audio(args: list[str], bitrate: str = "128k") -> list[str]:
    """
    Apply low latency audio settings to FFmpeg arguments.

    Enforces:
    - -ar 48000 (48kHz sample rate)
    - -ac 2 (stereo channels)
    - -b:a with the specified bitrate

    Args:
        args: List of existing FFmpeg arguments
        bitrate: Audio bitrate (default: "128k")

    Returns:
        Updated list of FFmpeg arguments with low latency audio settings
    """
    # Create a copy to avoid modifying the original list
    result_args = args.copy()

    # Low latency audio settings
    low_latency_audio_flags = [
        "-ar",
        "48000",  # 48kHz sample rate
        "-ac",
        "2",  # Stereo channels
        "-b:a",
        bitrate,  # Audio bitrate
    ]

    # Insert the low latency flags after the input specification
    # Find the last input file index to insert after it
    input_index = -1
    for i, arg in enumerate(result_args):
        if not arg.startswith("-") and not arg.startswith("[") and not arg.startswith("]"):
            # This is likely an input file
            input_index = i

    # Insert after the last input file, or at the beginning if no input found
    insert_index = input_index + 1 if input_index >= 0 else 0
    result_args[insert_index:insert_index] = low_latency_audio_flags

    return result_args
