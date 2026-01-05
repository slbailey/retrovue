"""Copy mode validation for video streaming."""


class CopyModeUnsupportedError(Exception):
    """Raised when copy mode is requested but codecs are incompatible."""

    def __init__(self, video_codec: str, audio_codec: str):
        self.video_codec = video_codec
        self.audio_codec = audio_codec
        super().__init__(
            f"Copy mode unsupported: requires H.264 Annex-B + AAC/MP2, "
            f"got {video_codec} + {audio_codec}"
        )


def can_copy(video_codec: str, audio_codec: str) -> bool:
    """
    Check if copy mode is supported for the given video and audio codecs.

    Copy mode is only supported for:
    - Video: H.264 (with Annex-B format)
    - Audio: AAC or MP2

    Args:
        video_codec: The video codec name (e.g., 'h264', 'hevc', 'vp9')
        audio_codec: The audio codec name (e.g., 'aac', 'mp2', 'opus', 'mp3')

    Returns:
        True if copy mode is supported, False otherwise
    """
    # Normalize codec names to lowercase for comparison
    video_codec_lower = video_codec.lower().strip()
    audio_codec_lower = audio_codec.lower().strip()

    # Supported video codecs for copy mode
    supported_video_codecs: set[str] = {"h264", "h.264", "avc", "x264"}

    # Supported audio codecs for copy mode
    supported_audio_codecs: set[str] = {"aac", "mp2"}

    # Check if both codecs are supported
    video_supported = video_codec_lower in supported_video_codecs
    audio_supported = audio_codec_lower in supported_audio_codecs

    return video_supported and audio_supported


def validate_copy_mode(video_codec: str, audio_codec: str) -> None:
    """
    Validate that copy mode is supported for the given codecs.

    Args:
        video_codec: The video codec name
        audio_codec: The audio codec name

    Raises:
        CopyModeUnsupportedError: If copy mode is not supported for the codecs
    """
    if not can_copy(video_codec, audio_codec):
        raise CopyModeUnsupportedError(video_codec, audio_codec)
