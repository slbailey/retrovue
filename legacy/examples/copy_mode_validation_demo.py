"""Demo script showing how to use the copy mode validation."""

import os
import sys

sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'src'))

from retrovue.validation.copy_mode import CopyModeUnsupportedError, can_copy, validate_copy_mode


def demo_copy_mode_validation():
    """Demonstrate copy mode validation functionality."""
    print("=== Copy Mode Validation Demo ===\n")
    
    # Test cases with different codec combinations
    test_cases = [
        ("h264", "aac", "Valid H.264 + AAC"),
        ("h264", "mp2", "Valid H.264 + MP2"),
        ("h265", "aac", "Invalid H.265 + AAC"),
        ("h264", "opus", "Invalid H.264 + Opus"),
        ("h264", "mp3", "Invalid H.264 + MP3"),
        ("vp9", "aac", "Invalid VP9 + AAC"),
        ("hevc", "opus", "Invalid HEVC + Opus"),
    ]
    
    print("Testing can_copy() function:")
    print("-" * 40)
    
    for video_codec, audio_codec, description in test_cases:
        result = can_copy(video_codec, audio_codec)
        status = "[OK] Supported" if result else "[NO] Not supported"
        print(f"{description:25} | {video_codec:6} + {audio_codec:6} | {status}")
    
    print("\nTesting validate_copy_mode() function:")
    print("-" * 50)
    
    for video_codec, audio_codec, description in test_cases:
        try:
            validate_copy_mode(video_codec, audio_codec)
            print(f"{description:25} | {video_codec:6} + {audio_codec:6} | [OK] Validation passed")
        except CopyModeUnsupportedError as e:
            print(f"{description:25} | {video_codec:6} + {audio_codec:6} | [NO] {e}")
    
    print("\n=== Integration Example ===")
    print("How to use in command builder:")
    print("-" * 30)
    
    def build_streaming_command(video_codec: str, audio_codec: str, use_copy_mode: bool = True):
        """Example of how to integrate copy mode validation in command building."""
        if use_copy_mode:
            try:
                validate_copy_mode(video_codec, audio_codec)
                print(f"[OK] Copy mode supported for {video_codec} + {audio_codec}")
                return "ffmpeg -c:v copy -c:a copy -f mpegts output.ts"
            except CopyModeUnsupportedError as e:
                print(f"[NO] Copy mode not supported: {e}")
                print("-> Switching to transcode mode...")
                return "ffmpeg -c:v libx264 -c:a aac -f mpegts output.ts"
        else:
            return "ffmpeg -c:v libx264 -c:a aac -f mpegts output.ts"
    
    # Example usage
    print("Building command for H.264 + AAC:")
    cmd1 = build_streaming_command("h264", "aac")
    print(f"Command: {cmd1}\n")
    
    print("Building command for H.265 + Opus:")
    cmd2 = build_streaming_command("h265", "opus")
    print(f"Command: {cmd2}\n")


if __name__ == "__main__":
    demo_copy_mode_validation()
