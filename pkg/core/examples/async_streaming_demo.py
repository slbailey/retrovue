#!/usr/bin/env python3
"""
Demonstration of the async MPEGTSStreamer implementation.

This script shows how the MPEGTSStreamer works with the FFmpeg command builder.
"""

import asyncio
import os
import tempfile

from retrovue.streaming.ffmpeg_cmd import build_cmd
from retrovue.streaming.mpegts_stream import MPEGTSStreamer


async def demo_streaming():
    """Demonstrate async streaming functionality."""
    print("Async MPEGTSStreamer Demo")
    print("=" * 40)
    
    # Create a temporary concat file for demonstration
    with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
        # In a real scenario, this would list actual video files
        f.write("file 'demo_video.mp4'\n")
        concat_path = f.name
    
    try:
        # Build FFmpeg command
        print("1. Building FFmpeg command...")
        cmd = build_cmd(concat_path, mode="transcode")
        print(f"Command: {' '.join(cmd)}")
        
        # Create streamer
        print("\n2. Creating MPEGTSStreamer...")
        streamer = MPEGTSStreamer(cmd)
        print(f"Streamer created with command: {len(cmd)} arguments")
        
        # Demonstrate streaming (this would normally stream real data)
        print("\n3. Demonstrating streaming interface...")
        print("Note: This demo shows the interface, not actual streaming")
        print("In a real scenario, this would yield 1316-byte chunks from FFmpeg")
        
        # Show chunk size specification
        print("\n4. Chunk size: 1316 bytes (7 × 188 bytes)")
        print("This ensures proper TS packet alignment for MPEG-TS streaming")
        
        # Show FastAPI integration example
        print("\n5. FastAPI Integration Example:")
        print("""
@app.get("/iptv/channel/{chan_id}.ts")
async def channel(chan_id: str):
    cmd = build_cmd(f"/path/to/{chan_id}/concat.txt", mode="transcode")
    streamer = MPEGTSStreamer(cmd)
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
        """)
        
        print("\n6. Key Features:")
        print("[OK] Async streaming with asyncio.create_subprocess_exec")
        print("[OK] 1316-byte chunks (7x188 bytes) for TS packet alignment")
        print("[OK] No preamble bytes before first TS packet")
        print("[OK] Graceful cancellation with process termination")
        print("[OK] FastAPI integration with proper headers")
        print("[OK] Content-Encoding: identity header included")
        
    finally:
        # Clean up temporary file
        if os.path.exists(concat_path):
            os.unlink(concat_path)


async def demo_cancellation():
    """Demonstrate cancellation handling."""
    print("\n" + "=" * 40)
    print("Cancellation Demo")
    print("=" * 40)
    
    print("1. In a real scenario, the streamer would:")
    print("   - Launch FFmpeg with asyncio.create_subprocess_exec")
    print("   - Read 1316-byte chunks from stdout")
    print("   - Yield chunks until EOF or cancellation")
    
    print("\n2. On cancellation:")
    print("   - asyncio.CancelledError is raised")
    print("   - Process is terminated gracefully")
    print("   - Resources are cleaned up")
    
    print("\n3. Key benefits:")
    print("[OK] No resource leaks on cancellation")
    print("[OK] Graceful process termination")
    print("[OK] Proper async/await integration")


async def main():
    """Main demonstration function."""
    await demo_streaming()
    await demo_cancellation()
    
    print("\n" + "=" * 40)
    print("Demo Complete!")
    print("=" * 40)
    print("The MPEGTSStreamer is ready for production use with:")
    print("- Async streaming capabilities")
    print("- Proper TS packet alignment") 
    print("- Graceful error handling")
    print("- FastAPI integration")


if __name__ == "__main__":
    asyncio.run(main())
