"""
Demo script showing how to use MPEGTSWatchdog.

This example demonstrates the watchdog's automatic restart capabilities
and metrics tracking.
"""

import asyncio
import logging
import sys
from pathlib import Path

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from retrovue.streaming.watchdog import MPEGTSWatchdog

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def demo_watchdog():
    """Demonstrate the watchdog functionality."""
    
    # Example FFmpeg command (you would replace this with your actual command)
    cmd = [
        "ffmpeg",
        "-f", "lavfi",
        "-i", "testsrc=duration=10:size=320x240:rate=1",
        "-f", "mpegts",
        "-"
    ]
    
    # Create watchdog with 5-second stall timeout
    watchdog = MPEGTSWatchdog(cmd, stall_timeout=5.0)
    
    logger.info("Starting MPEGTSWatchdog demo...")
    logger.info(f"Initial metrics: {watchdog.get_metrics()}")
    
    try:
        # Stream for a limited time to demonstrate functionality
        chunk_count = 0
        start_time = asyncio.get_event_loop().time()
        
        async for chunk in watchdog.stream():
            chunk_count += 1
            logger.info(f"Received chunk {chunk_count}, size: {len(chunk)} bytes")
            
            # Print metrics every 10 chunks
            if chunk_count % 10 == 0:
                metrics = watchdog.get_metrics()
                logger.info(f"Metrics: {metrics}")
            
            # Stop after 30 seconds or 50 chunks
            elapsed = asyncio.get_event_loop().time() - start_time
            if elapsed > 30.0 or chunk_count >= 50:
                break
                
    except KeyboardInterrupt:
        logger.info("Demo interrupted by user")
    except Exception as e:
        logger.error(f"Demo error: {e}")
    finally:
        # Final metrics
        final_metrics = watchdog.get_metrics()
        logger.info(f"Final metrics: {final_metrics}")
        logger.info(f"Total chunks received: {chunk_count}")


if __name__ == "__main__":
    print("MPEGTSWatchdog Demo")
    print("==================")
    print("This demo shows the watchdog's automatic restart capabilities.")
    print("Press Ctrl+C to stop the demo.\n")
    
    try:
        asyncio.run(demo_watchdog())
    except KeyboardInterrupt:
        print("\nDemo stopped by user.")
    except Exception as e:
        print(f"Demo failed: {e}")
