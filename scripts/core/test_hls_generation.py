#!/usr/bin/env python3
"""
HLS Generation Test Script

This script tests HLS playlist generation using FFmpeg with the target flags
specified in the playout documentation.
"""

import subprocess
import sys
from pathlib import Path


def create_test_video():
    """Create a test video file for HLS generation."""
    print("Creating test video...")
    
    # Create a simple test video using FFmpeg
    test_video = "test_video.mp4"
    
    # Generate a 30-second test video with color bars and audio tone
    cmd = [
        "ffmpeg", "-y",  # Overwrite output file
        "-f", "lavfi",   # Use libavfilter
        "-i", "testsrc2=duration=30:size=1280x720:rate=30",  # Color bars
        "-f", "lavfi",   # Audio source
        "-i", "sine=frequency=1000:duration=30",  # 1kHz tone
        "-c:v", "libx264",  # H.264 video codec
        "-c:a", "aac",      # AAC audio codec
        "-preset", "fast",  # Fast encoding
        "-crf", "23",       # Good quality
        test_video
    ]
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        print(f"✅ Test video created: {test_video}")
        return test_video
    except subprocess.CalledProcessError as e:
        print(f"❌ Failed to create test video: {e}")
        print(f"FFmpeg stderr: {e.stderr}")
        return None
    except FileNotFoundError:
        print("❌ FFmpeg not found. Please install FFmpeg.")
        return None

def test_hls_generation(input_video: str):
    """Test HLS generation with target flags."""
    print("Testing HLS generation...")
    
    # Create output directory
    output_dir = Path("test_hls_output")
    output_dir.mkdir(exist_ok=True)
    
    # HLS generation command with target flags
    cmd = [
        "ffmpeg", "-y",  # Overwrite output files
        "-i", input_video,
        "-f", "hls",                    # HLS format
        "-hls_time", "2",              # 2-second segments
        "-hls_list_size", "5",         # Keep 5 segments
        "-hls_flags", "delete_segments+program_date_time",  # Auto-delete + timestamps
        "-hls_segment_filename", str(output_dir / "segment_%03d.ts"),
        "-hls_playlist_type", "event",
        "-hls_allow_cache", "0",
        str(output_dir / "playlist.m3u8")
    ]
    
    print(f"Running: {' '.join(cmd)}")
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        print("✅ HLS generation completed successfully")
        return output_dir
    except subprocess.CalledProcessError as e:
        print(f"❌ HLS generation failed: {e}")
        print(f"FFmpeg stderr: {e.stderr}")
        return None

def analyze_playlist(playlist_path: Path):
    """Analyze the generated HLS playlist."""
    print("Analyzing HLS playlist...")
    
    try:
        with open(playlist_path) as f:
            content = f.read()
        
        lines = content.strip().split('\n')
        
        print(f"📄 Playlist content ({len(lines)} lines):")
        print("-" * 50)
        for i, line in enumerate(lines[:20]):  # Show first 20 lines
            print(f"{i+1:2d}: {line}")
        if len(lines) > 20:
            print(f"... and {len(lines) - 20} more lines")
        print("-" * 50)
        
        # Analyze playlist structure
        extm3u = "#EXTM3U" in content
        version = "EXT-X-VERSION" in content
        target_duration = "EXT-X-TARGETDURATION" in content
        program_date_time = "EXT-X-PROGRAM-DATE-TIME" in content
        segments = [line for line in lines if line.endswith('.ts')]
        
        print(f"✅ EXTM3U header: {extm3u}")
        print(f"✅ Version info: {version}")
        print(f"✅ Target duration: {target_duration}")
        print(f"✅ Program date-time: {program_date_time}")
        print(f"✅ Segments found: {len(segments)}")
        
        # Check segment files
        segment_dir = playlist_path.parent
        existing_segments = []
        for segment in segments:
            segment_path = segment_dir / segment
            if segment_path.exists():
                size = segment_path.stat().st_size
                existing_segments.append((segment, size))
        
        print(f"✅ Segment files: {len(existing_segments)}/{len(segments)}")
        for segment, size in existing_segments[:5]:  # Show first 5
            print(f"   - {segment}: {size:,} bytes")
        
        return {
            "valid": extm3u and version and target_duration and program_date_time,
            "segments": len(segments),
            "existing_segments": len(existing_segments)
        }
        
    except Exception as e:
        print(f"❌ Failed to analyze playlist: {e}")
        return {"valid": False, "error": str(e)}

def test_vlc_compatibility(playlist_path: Path):
    """Test VLC compatibility (simulation)."""
    print("Testing VLC compatibility...")
    
    # Check if VLC is available
    try:
        result = subprocess.run(["vlc", "--version"], capture_output=True, text=True)
        vlc_available = result.returncode == 0
    except FileNotFoundError:
        vlc_available = False
    
    if vlc_available:
        print("✅ VLC is available")
        print("📺 To test in VLC:")
        print("   1. Open VLC Media Player")
        print("   2. Go to: Media → Open Network Stream")
        print(f"   3. Enter: file://{playlist_path.absolute()}")
        print("   4. Click Play")
    else:
        print("⚠️  VLC not found - install VLC to test playback")
        print("📺 Manual test instructions:")
        print("   1. Install VLC Media Player")
        print("   2. Open VLC")
        print("   3. Go to: Media → Open Network Stream")
        print(f"   4. Enter: file://{playlist_path.absolute()}")
        print("   5. Click Play")

def cleanup_test_files():
    """Clean up test files."""
    print("Cleaning up test files...")
    
    files_to_remove = [
        "test_video.mp4",
        "test_hls_output"
    ]
    
    for item in files_to_remove:
        path = Path(item)
        if path.exists():
            if path.is_file():
                path.unlink()
                print(f"🗑️  Removed file: {item}")
            elif path.is_dir():
                import shutil
                shutil.rmtree(path)
                print(f"🗑️  Removed directory: {item}")

def main():
    """Main test function."""
    print("🎬 HLS Generation Test")
    print("=" * 50)
    
    # Check FFmpeg availability
    try:
        result = subprocess.run(["ffmpeg", "-version"], capture_output=True, text=True)
        if result.returncode != 0:
            raise FileNotFoundError
        print("✅ FFmpeg is available")
    except FileNotFoundError:
        print("❌ FFmpeg not found. Please install FFmpeg.")
        return 1
    
    # Create test video
    test_video = create_test_video()
    if not test_video:
        return 1
    
    # Generate HLS
    output_dir = test_hls_generation(test_video)
    if not output_dir:
        return 1
    
    # Analyze results
    playlist_path = output_dir / "playlist.m3u8"
    if playlist_path.exists():
        analysis = analyze_playlist(playlist_path)
        
        if analysis["valid"]:
            print("🎉 HLS generation test PASSED")
            test_vlc_compatibility(playlist_path)
        else:
            print("❌ HLS generation test FAILED")
            return 1
    else:
        print("❌ Playlist file not found")
        return 1
    
    # Ask about cleanup
    print("\n" + "=" * 50)
    cleanup = input("Clean up test files? (y/N): ").lower().strip()
    if cleanup in ['y', 'yes']:
        cleanup_test_files()
    else:
        print(f"📁 Test files preserved in: {output_dir.absolute()}")
    
    return 0

if __name__ == "__main__":
    sys.exit(main())

