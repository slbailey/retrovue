# Phase 0 Quick Start Guide

## Overview

Phase 0 provides a simple linear streaming setup with:
- Fixed 30-minute grid (blocks start at :00 and :30)
- One program asset (reused every block)
- One filler asset (looped continuously)
- Join-in-progress support (viewers can tune in mid-block)

## Starting Phase 0

### Prerequisites

1. Ensure you have the asset files:
   - Program asset: `assets/samplecontent.mp4` (~1500 seconds / 25 minutes)
   - Filler asset: `assets/filler.mp4` (~3650 seconds / ~1 hour)

2. Install ffmpeg (required for playout):
   ```bash
   sudo apt-get install ffmpeg  # Ubuntu/Debian
   # or
   brew install ffmpeg  # macOS
   ```

3. Activate the virtual environment:
   ```bash
   cd /opt/retrovue/pkg/core
   source .venv/bin/activate
   ```

### Start ProgramDirector with Phase 0

**Using ffmpeg (recommended for testing):**
```bash
RETROVUE_USE_FFMPEG=1 retrovue program-director start \
  --mock-schedule-grid \
  --program-asset /opt/retrovue/assets/samplecontent.mp4 \
  --phase0-program-duration 1500 \
  --filler-asset /opt/retrovue/assets/filler.mp4 \
  --filler-duration 3650 \
  --port 8000
```

**Or without the environment variable (will auto-detect if Air is not available):**
```bash
retrovue program-director start \
  --mock-schedule-grid \
  --program-asset /opt/retrovue/assets/samplecontent.mp4 \
  --phase0-program-duration 1500 \
  --filler-asset /opt/retrovue/assets/filler.mp4 \
  --filler-duration 3650 \
  --port 8000
```

**Note:** The system will automatically use ffmpeg if `retrovue_air` is not found, or if `RETROVUE_USE_FFMPEG=1` is set.

**Note:** The program duration should be less than 30 minutes (1800 seconds) to fit within a grid block. The filler fills the remainder of each 30-minute block.

## Connecting to the Stream

Once ProgramDirector is running, you can connect to the channel stream:

### Using curl

```bash
# Stream to stdout (save to file)
curl http://localhost:8000/channel/test-1.ts > output.ts

# Stream to VLC (if VLC is installed)
curl http://localhost:8000/channel/test-1.ts | vlc -
```

### Using VLC directly

1. Open VLC
2. Media → Open Network Stream
3. Enter: `http://localhost:8000/channel/test-1.ts`
4. Click Play

### Using ffplay

```bash
ffplay http://localhost:8000/channel/test-1.ts
```

### Using a web browser

Some browsers can play MPEG-TS streams directly:
- Navigate to: `http://localhost:8000/channel/test-1.ts`

## How It Works

1. **Grid Alignment**: The system uses a fixed 30-minute grid. Blocks start at :00 and :30 (e.g., 14:00, 14:30, 15:00).

2. **Program vs Filler**:
   - First ~25 minutes of each block: Program content (`samplecontent.mp4`)
   - Remaining ~5 minutes: Filler content (`filler.mp4`)

3. **Join-in-Progress**: When a viewer connects:
   - If they join during the program segment, playback starts at the current position in the program
   - If they join during the filler segment, playback starts at the current position in the filler
   - The filler asset loops continuously (never restarts from 00:00)

4. **Viewer Lifecycle**:
   - First viewer connects → Playout engine starts
   - Last viewer disconnects → Playout engine stops
   - Multiple viewers share the same stream (fanout)

## Testing Join-in-Progress

To test join-in-progress behavior:

1. Start the server
2. Connect a viewer at different times:
   - At :00 or :30 (block start) → Should start at beginning of program
   - At :15 (mid-program) → Should join mid-program
   - At :28 (in filler) → Should join mid-filler

## Troubleshooting

### "Channel not available" error

- Ensure ProgramDirector is running
- Check that asset paths are correct and files exist
- Verify program duration is less than 30 minutes (1800 seconds)

### No video/audio

- Check that the playout engine (Air) is running (it starts when first viewer connects)
- Verify asset files are valid MP4 files
- Check server logs for errors

### Stream stops

- The stream stops when the last viewer disconnects
- Reconnect to restart the stream

## Example Session

```bash
# Terminal 1: Start ProgramDirector
cd /opt/retrovue/pkg/core
source .venv/bin/activate
retrovue program-director start \
  --mock-schedule-grid \
  --program-asset /opt/retrovue/assets/samplecontent.mp4 \
  --phase0-program-duration 1500 \
  --filler-asset /opt/retrovue/assets/filler.mp4 \
  --filler-duration 3650

# Terminal 2: Connect to stream
curl http://localhost:8000/channel/test-1.ts | vlc -
```

## API Endpoints

- `GET /channels` - List available channels
- `GET /channel/{channel_id}.ts` - Stream channel (e.g., `/channel/test-1.ts`)
- `POST /admin/emergency` - Emergency override (no-op in Phase 0)
