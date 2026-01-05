#!/usr/bin/env python3
"""
Example FastAPI route using the async MPEGTSStreamer.

This demonstrates how to use the MPEGTSStreamer with FastAPI for IPTV streaming.
"""

from fastapi import FastAPI
from fastapi.responses import StreamingResponse

from retrovue.streaming.ffmpeg_cmd import build_cmd
from retrovue.streaming.mpegts_stream import MPEGTSStreamer

app = FastAPI()


@app.get("/iptv/channel/{chan_id}.ts")
async def channel(chan_id: str):
    """
    IPTV channel streaming endpoint.
    
    Args:
        chan_id: Channel identifier
        
    Returns:
        StreamingResponse with MPEG-TS video stream
    """
    # Build FFmpeg command for the channel
    # In a real implementation, you'd look up the channel configuration
    concat_path = f"/path/to/channels/{chan_id}/concat.txt"
    cmd = build_cmd(concat_path, mode="transcode")
    
    # Create streamer
    streamer = MPEGTSStreamer(cmd)
    
    # Return streaming response
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


@app.get("/iptv/channel/{chan_id}/copy.ts")
async def channel_copy(chan_id: str):
    """
    IPTV channel streaming endpoint using copy mode for better performance.
    """
    concat_path = f"/path/to/channels/{chan_id}/concat.txt"
    cmd = build_cmd(concat_path, mode="copy")
    
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


@app.get("/iptv/channel/{chan_id}/hq.ts")
async def channel_hq(chan_id: str):
    """
    High-quality IPTV channel streaming endpoint.
    """
    concat_path = f"/path/to/channels/{chan_id}/concat.txt"
    cmd = build_cmd(
        concat_path,
        mode="transcode",
        video_preset="medium",  # Higher quality
        audio_bitrate="320k",   # Higher audio quality
        gop=60
    )
    
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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
