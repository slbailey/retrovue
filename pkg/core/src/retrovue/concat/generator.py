"""
Concat file generator for Retrovue.

This module provides utilities for generating FFmpeg concat files that alternate
between episode segments and advertisements, enabling commercial insertion into
video streams.
"""

from __future__ import annotations

import logging
import os
import tempfile

logger = logging.getLogger(__name__)


def generate_concat_file(episode_segments: list[str], ads: list[str]) -> str:
    """
    Generate a temporary concat file with alternating episode segments and ads.

    Creates a concat file that follows the pattern:
    episode_segment_1, ad_1, episode_segment_2, ad_2, ...

    Args:
        episode_segments: List of paths to episode segment files
        ads: List of paths to advertisement files

    Returns:
        Path to the generated temporary concat file

    Example:
        >>> segments = ["ep1_seg1.mp4", "ep1_seg2.mp4", "ep1_seg3.mp4"]
        >>> ads = ["ad1.mp4", "ad2.mp4"]
        >>> concat_path = generate_concat_file(segments, ads)
        >>> # Creates concat file with: seg1, ad1, seg2, ad2, seg3
    """
    if not episode_segments:
        raise ValueError("At least one episode segment is required")

    # Create alternating content
    concat_content = []

    # Add first episode segment
    concat_content.append(f"file '{episode_segments[0]}'")

    # Alternate between ads and remaining segments
    for i in range(1, len(episode_segments)):
        # Add ad if available
        if i - 1 < len(ads):
            concat_content.append(f"file '{ads[i - 1]}'")

        # Add next episode segment
        concat_content.append(f"file '{episode_segments[i]}'")

    # Add any remaining ads after the last segment
    remaining_ads = len(ads) - (len(episode_segments) - 1)
    for i in range(remaining_ads):
        if len(episode_segments) - 1 + i < len(ads):
            concat_content.append(f"file '{ads[len(episode_segments) - 1 + i]}'")

    # Write to temporary file
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write("\n".join(concat_content))
        concat_file_path = f.name

    logger.info(f"Generated concat file with {len(concat_content)} entries: {concat_file_path}")
    return concat_file_path


def validate_concat_file(path: str) -> bool:
    """
    Validate that all files referenced in a concat file exist.

    Args:
        path: Path to the concat file to validate

    Returns:
        True if all files exist, False otherwise

    Example:
        >>> concat_path = generate_concat_file(segments, ads)
        >>> is_valid = validate_concat_file(concat_path)
        >>> print(f"Concat file is valid: {is_valid}")
    """
    if not os.path.exists(path):
        logger.error(f"Concat file does not exist: {path}")
        return False

    try:
        with open(path) as f:
            lines = f.readlines()

        for line_num, line in enumerate(lines, 1):
            line = line.strip()
            if not line:
                continue

            if not line.startswith("file '"):
                logger.warning(f"Invalid line format at line {line_num}: {line}")
                continue

            # Extract file path from "file 'path'" format
            if line.startswith("file '") and line.endswith("'"):
                file_path = line[6:-1]  # Remove "file '" and "'"
            else:
                logger.warning(f"Invalid file line format at line {line_num}: {line}")
                continue

            # Check if file exists
            if not os.path.exists(file_path):
                logger.error(f"Referenced file does not exist: {file_path} (line {line_num})")
                return False

        logger.info(f"Concat file validation successful: {path}")
        return True

    except Exception as e:
        logger.error(f"Error validating concat file {path}: {e}")
        return False


def read_concat_file(path: str) -> list[str]:
    """
    Read and return the contents of a concat file as a list of file paths.

    Args:
        path: Path to the concat file

    Returns:
        List of file paths referenced in the concat file

    Example:
        >>> concat_path = generate_concat_file(segments, ads)
        >>> file_paths = read_concat_file(concat_path)
        >>> print(f"Concat file contains {len(file_paths)} files")
    """
    if not os.path.exists(path):
        raise FileNotFoundError(f"Concat file does not exist: {path}")

    file_paths = []

    with open(path) as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue

            if line.startswith("file '"):
                # Extract file path from "file 'path'" format
                if line.endswith("'"):
                    file_path = line[6:-1]  # Remove "file '" and "'"
                    file_paths.append(file_path)
                else:
                    logger.warning(f"Invalid file line format at line {line_num}: {line}")
            else:
                logger.warning(f"Invalid line format at line {line_num}: {line}")

    return file_paths


def cleanup_concat_file(path: str) -> None:
    """
    Clean up a temporary concat file.

    Args:
        path: Path to the concat file to delete

    Example:
        >>> concat_path = generate_concat_file(segments, ads)
        >>> # Use the concat file...
        >>> cleanup_concat_file(concat_path)
    """
    try:
        if os.path.exists(path):
            os.unlink(path)
            logger.info(f"Cleaned up concat file: {path}")
    except Exception as e:
        logger.error(f"Error cleaning up concat file {path}: {e}")


def create_episode_with_ads(
    episode_path: str, ad_paths: list[str], break_points: list[float]
) -> str:
    """
    Create a concat file for an episode with ads inserted at break points.

    This is a higher-level function that combines episode segmentation with
    ad insertion for a complete commercial insertion workflow.

    Args:
        episode_path: Path to the main episode file
        ad_paths: List of advertisement file paths
        break_points: List of timestamps where ads should be inserted

    Returns:
        Path to the generated concat file

    Example:
        >>> episode = "episode.mp4"
        >>> ads = ["ad1.mp4", "ad2.mp4"]
        >>> breaks = [300.0, 600.0]  # 5 and 10 minutes
        >>> concat_path = create_episode_with_ads(episode, ads, breaks)
    """
    # This would integrate with the segment_episode function from mpegts_stream.py
    # For now, this is a placeholder for the complete workflow
    logger.info(
        f"Creating episode with ads: {episode_path}, {len(ad_paths)} ads, {len(break_points)} breaks"
    )

    # In a complete implementation, this would:
    # 1. Segment the episode at break points
    # 2. Create alternating segments and ads
    # 3. Generate the concat file

    # For now, return a simple concat file with the episode
    return generate_concat_file([episode_path], ad_paths)
