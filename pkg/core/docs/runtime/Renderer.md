# RetroVue Runtime — Renderer

_Related: [Runtime: Channel manager](channel_manager.md) • [Runtime: Producer lifecycle](ProducerLifecycle.md) • [Domain: Playout pipeline](../domain/PlayoutPipeline.md)_

> Component responsible for converting a Producer's media source into a playable output stream.

## Purpose

A Renderer is the component responsible for taking a Producer's media source and converting it into a playable output stream. It defines how content is processed, encoded, and delivered — bridging the gap between high-level scheduling (managed by the ChannelManager) and the actual audiovisual output that viewers receive.

## Core Model / Scope

Renderers handle all aspects of playout execution, including:

- **Launching and controlling FFmpeg** (or other media engines)
- **Applying encoding, muxing, or streaming parameters**
- **Managing the output target** (e.g., MPEG-TS file, HLS stream, RTMP endpoint)
- **Responding to play, stop, or switch events** initiated by the ChannelManager

Each renderer consumes one Producer at a time.

When a channel switches from one producer to another, the renderer seamlessly transitions to the new input source without requiring architectural changes to the producers themselves.

## Relationship to Other Components

### Producer

- **Producer = "What to play"** — Provides the media source (input URL, file path, or stream)
- **Renderer = "How to play it"** — Converts that source into a playable output stream
- Producers are input-driven and stateless; they provide FFmpeg-compatible input specifiers
- Renderers are execution-driven and stateful; they manage FFmpeg processes and output streams

### ChannelManager

- **ChannelManager = "When to play it"** — Determines when to start/stop playback and which Producer to use
- ChannelManager selects the Producer, then hands the Producer's input URL to the Renderer
- ChannelManager manages the Renderer lifecycle (start, stop, switch)
- ChannelManager does not directly control FFmpeg; it uses the Renderer interface

### ProgramDirector

- **ProgramDirector = "Why it's playing right now"** — Sets global mode and emergency overrides
- ProgramDirector coordinates across channels but does not manage Renderers directly
- Renderers respond to mode changes via ChannelManager

## Contract / Interface

Every renderer implementation follows a consistent interface, typically including:

### Core Methods

- **`render(input_url: str) → bool`**: Begins playback of the specified producer input
  - Launches FFmpeg (or equivalent) with the provided input
  - Applies encoding, muxing, and streaming parameters
  - Returns `True` if playback started successfully

- **`stop() → bool`**: Gracefully stops the current output
  - Terminates the FFmpeg process cleanly
  - Closes output streams and releases resources
  - Returns `True` if stop was successful

- **`switch_to(new_input_url: str) → bool`**: (Optional) Seamlessly transitions to a new input source
  - Switches FFmpeg input without interrupting the output stream
  - Enables live transitions between producers
  - Returns `True` if switch was successful

### Additional Methods

- **`get_output_url() → str | None`**: Returns the output stream URL (e.g., HTTP endpoint, file path)
- **`get_status() → RendererStatus`**: Returns current renderer status (stopped, starting, running, stopping, error)
- **`health_check() → dict[str, Any]`**: Returns health metrics and diagnostics

## Design Principles

### Input Source Flexibility

Renderers should be designed to support multiple input types:

- **File paths**: Local media files (e.g., `/path/to/video.mp4`)
- **lavfi sources**: FFmpeg filter inputs (e.g., `lavfi:testsrc=size=1920x1080`)
- **Network streams**: RTMP, HLS, HTTP streams (e.g., `rtmp://example.com/stream`)
- **Concat files**: FFmpeg concat demuxer inputs for seamless file concatenation

### Process Management

Renderers must encapsulate all process management, error recovery, and logging related to FFmpeg:

- **Process lifecycle**: Launch, monitor, and terminate FFmpeg processes
- **Error handling**: Detect and recover from FFmpeg failures
- **Logging**: Capture and expose FFmpeg stderr for debugging
- **Health monitoring**: Track process health and stream quality

### Output Target Management

Renderers manage the output target configuration:

- **MPEG-TS streams**: Continuous transport streams for IPTV playback
- **HLS streams**: HTTP Live Streaming for adaptive bitrate delivery
- **RTMP endpoints**: Real-time streaming to external services
- **File output**: Recording streams to local files

### Seamless Transitions

Renderers must support seamless transitions between producers:

- **Switch without interruption**: Change input source without breaking the output stream
- **State preservation**: Maintain encoding parameters and stream continuity
- **Error recovery**: Fallback to safe state if transition fails

## Execution Model

### Initialization

1. ChannelManager selects a Producer based on schedule and mode
2. Producer provides an input URL via `get_input_url()`
3. ChannelManager instantiates or reuses a Renderer for the channel
4. Renderer receives the input URL and configuration

### Playback Start

1. ChannelManager calls `render(input_url)`
2. Renderer launches FFmpeg with the input URL
3. Renderer applies encoding parameters (codec, bitrate, format)
4. Renderer starts output stream and returns output URL
5. ChannelManager exposes output URL to viewers

### Playback Stop

1. ChannelManager calls `stop()` when last viewer disconnects
2. Renderer gracefully terminates FFmpeg process
3. Renderer closes output streams and releases resources
4. Renderer returns to stopped state

### Producer Switch

1. ChannelManager determines a different Producer should be active
2. ChannelManager calls `switch_to(new_input_url)` if supported
3. Renderer transitions FFmpeg input without stopping output
4. If switch is not supported, ChannelManager calls `stop()` then `render(new_input_url)`

## Failure / Fallback Behavior

If a Renderer fails to start or crashes during playback:

- **ChannelManager detects failure** via health checks or process monitoring
- **ChannelManager attempts recovery** by restarting the Renderer
- **If recovery fails**, ChannelManager may switch to an emergency Producer
- **ChannelManager reports failure** to ProgramDirector for system-wide coordination

## Naming Rules

- **"Renderer"** is always the component that executes FFmpeg and manages output streams
- **"Producer"** is always the component that provides input sources
- **"Input URL"** is the FFmpeg-compatible source string provided by a Producer
- **"Output URL"** is the playable stream endpoint provided by a Renderer

## Implementation Notes

### FFmpeg Integration

Renderers are the primary interface to FFmpeg in RetroVue:

- **Command construction**: Build FFmpeg commands from input URLs and configuration
- **Process management**: Launch and monitor FFmpeg subprocesses
- **Stream handling**: Read FFmpeg stdout and yield stream chunks
- **Error monitoring**: Capture and parse FFmpeg stderr for diagnostics

### Encoding Parameters

Renderers apply encoding parameters based on channel configuration:

- **Video codec**: H.264 (libx264) for broad compatibility
- **Audio codec**: AAC for audio encoding
- **Output format**: MPEG-TS for transport stream delivery
- **Quality settings**: Bitrate, preset, and tuning for performance

### Stream Delivery

Renderers manage stream delivery to viewers:

- **HTTP streaming**: Serve MPEG-TS streams via HTTP endpoints
- **Fanout model**: Single FFmpeg process serves multiple viewers
- **Chunked transfer**: Stream data in TS packet-aligned chunks
- **Content-Type headers**: Proper MIME types for client compatibility

## See Also

- [Runtime: Channel manager](channel_manager.md) - Renderer lifecycle management
- [Runtime: Producer lifecycle](ProducerLifecycle.md) - Producer interface and usage
- [Domain: Playout pipeline](../domain/PlayoutPipeline.md) - Overall playout architecture
- [Architecture overview](../architecture/ArchitectureOverview.md) - System context and boundaries



