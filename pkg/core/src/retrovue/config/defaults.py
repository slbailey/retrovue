"""Default configuration values for Retrovue streaming."""

# File reading configuration
READ_FROM_FILES_LIVE = True  # Uses -re flag for live file reading

# FFprobe configuration
PROBE_SIZE = "10M"
ANALYZE_DURATION = "2M"

# MPEG-TS streaming configuration
ENABLE_RESEND_HEADERS = True
ENABLE_INITIAL_DISCONTINUITY = True

# Chunk size for streaming
CHUNK_SIZE = 1316


def ts_mux_flags() -> str:
    """
    Generate MPEG-TS mux flags string combining enabled flags.

    Returns:
        A single -mpegts_flags string with enabled flags like:
        "+initial_discontinuity+resend_headers"
    """
    flags = []

    if ENABLE_INITIAL_DISCONTINUITY:
        flags.append("initial_discontinuity")

    if ENABLE_RESEND_HEADERS:
        flags.append("resend_headers")

    if not flags:
        return ""

    return "+" + "+".join(flags)


def validate_ffmpeg_flags(flags: list[str]) -> list[str]:
    """
    Validate FFmpeg flags to prevent invalid combinations.

    Args:
        flags: List of FFmpeg flags to validate

    Returns:
        Validated list of flags with invalid combinations removed

    Raises:
        ValueError: If invalid flag combinations are detected
    """
    # Clean and filter flags first
    cleaned_flags = [flag.strip() for flag in flags if flag.strip()]

    invalid_combinations = []

    # Check for MP4-only flags in non-MP4 contexts
    mp4_only_flags = ["faststart", "empty_moov", "frag_keyframe", "frag_custom"]
    has_mp4_flags = any(
        flag.startswith("-movflags") and any(mp4_flag in flag for mp4_flag in mp4_only_flags)
        for flag in cleaned_flags
    )

    # Check for MPEG-TS specific flags
    has_mpegts_flags = any(flag.startswith("-mpegts_flags") for flag in cleaned_flags)

    # If we have MP4-only flags but also MPEG-TS flags, that's invalid
    if has_mp4_flags and has_mpegts_flags:
        invalid_combinations.append("MP4-only movflags with MPEG-TS flags")

    # Check for conflicting container formats
    container_flags = [flag for flag in cleaned_flags if flag.startswith("-f ")]
    if len(container_flags) > 1:
        invalid_combinations.append("Multiple container format flags")

    # Check for conflicting streaming flags
    streaming_flags = [
        flag
        for flag in cleaned_flags
        if any(stream_flag in flag for stream_flag in ["-re", "-fflags", "-avoid_negative_ts"])
    ]
    if len(streaming_flags) > 3:  # Allow reasonable number of streaming flags
        invalid_combinations.append("Too many streaming flags")

    if invalid_combinations:
        raise ValueError(
            f"Invalid FFmpeg flag combinations detected: {', '.join(invalid_combinations)}"
        )

    # Filter out obviously problematic flags
    validated_flags = []
    for flag in cleaned_flags:
        # Skip flags that are clearly invalid
        if flag.startswith("-movflags") and has_mpegts_flags:
            continue  # Skip MP4 flags when using MPEG-TS

        validated_flags.append(flag)

    return validated_flags


def get_default_streaming_flags() -> list[str]:
    """
    Get default streaming flags for MPEG-TS streaming.

    Returns:
        List of default FFmpeg flags for streaming
    """
    flags = []

    if READ_FROM_FILES_LIVE:
        flags.append("-re")

    # Add MPEG-TS specific flags
    ts_flags = ts_mux_flags()
    if ts_flags:
        flags.append(f"-mpegts_flags {ts_flags}")

    # Add probe configuration
    flags.extend([f"-probesize {PROBE_SIZE}", f"-analyzeduration {ANALYZE_DURATION}"])

    return flags
