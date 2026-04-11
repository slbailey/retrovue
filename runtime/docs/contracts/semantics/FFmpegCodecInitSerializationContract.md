# FFmpeg Codec Init Serialization Contract (AIR)

**Classification**: Coordination Contract (Layer 2)
**Owner**: `RealAssetSource`, `FFmpegDecoder`, `EncoderPipeline`
**Derives From**: INV-SEAM-001 (Clock Isolation), INV-SEAM-SEG-006 (No Decoder Lifecycle on Fill Thread)
**Scope**: AIR runtime playout engine — all FFmpeg codec initialization paths

---

## Preamble

FFmpeg's internal codec initialization (`avformat_open_input`, `avformat_find_stream_info`,
`avcodec_open2`) writes to global state: FFT codelet tables, codec-specific static lookup tables, and
transform initialization via `AVOnce` / `pthread_once`. These global writes are not
fully serialized within FFmpeg when multiple threads call `avcodec_open2` concurrently
— even on separate `AVCodecContext` instances.

AIR runs up to four concurrent FFmpeg consumers:

| Thread | Component | FFmpeg Operation |
|--------|-----------|-----------------|
| SeamPreparer worker | `RealAssetSource::ProbeAsset()` | `avformat_find_stream_info` → internal `avcodec_open2` |
| SeamPreparer worker | `FFmpegDecoderAdapter::Open()` | `avformat_find_stream_info`, `avcodec_open2` (video + audio) |
| Fill thread | `FFmpegDecoder` decode loop | `avcodec_send_packet`, `avcodec_receive_frame` |
| Encoder thread | `EncoderPipeline::open()` | `avcodec_open2` (video encoder + audio encoder) |

Without serialization, concurrent codec initialization produces data races in
FFmpeg's internal global state, leading to SIGSEGV crashes (observed in
`ff_tx_init_subtx` during AAC SBR context initialization on the SeamPreparer
worker thread while the fill thread was actively decoding).

**Steady-state decode/encode operations** (`avcodec_send_packet`, `avcodec_receive_frame`,
`avcodec_send_frame`, `avcodec_receive_packet`) on separate `AVCodecContext` instances
are safe to run concurrently and MUST NOT be serialized (serializing them would
violate clock isolation).

---

## Definitions

- **Codec initialization**: Any call to `avformat_open_input()`, `avformat_find_stream_info()`,
  or `avcodec_open2()`. `avformat_open_input` performs format-level probing that can trigger
  codec registration. `avformat_find_stream_info` internally opens codecs for stream analysis.
  `avcodec_open2` explicitly initializes codec global tables.
- **Steady-state operation**: `avcodec_send_packet`, `avcodec_receive_frame`,
  `avcodec_send_frame`, `avcodec_receive_packet`, `av_read_frame` — operations on
  an already-initialized codec context.
- **Init guard**: The process-wide mutex (`retrovue::decode::ffmpeg_init_mutex()`)
  that serializes all codec initialization calls.

---

## INV-FFMPEG-CODEC-INIT-SERIALIZATION-001: Codec Init Serialization

### Statement

**All FFmpeg codec initialization calls (`avformat_open_input`, `avformat_find_stream_info`,
`avcodec_open2`) MUST be serialized across all threads within the AIR process via a single
process-wide mutex.**

This applies to every call site:

1. `RealAssetSource::ProbeAsset()` — `avformat_open_input` + `avformat_find_stream_info`
2. `FFmpegDecoder::Open()` — `avformat_open_input` + `avformat_find_stream_info` + `InitializeCodec` + `InitializeAudioCodec`
3. `EncoderPipeline::open()` — `avcodec_open2` (video encoder) + `avcodec_open2` (audio encoder)

The mutex MUST be held for the duration of the initialization sequence (from
`avformat_open_input` through `avcodec_open2` for all streams). It MUST be
released before steady-state decode/encode begins.

### Rationale

FFmpeg's internal global state (FFT codelet tables in `tx.c`, codec-specific
static tables initialized via `AVOnce` in SBR/AAC/etc.) is written during
`avcodec_open2`. Concurrent `avcodec_open2` on the same codec type races on
these tables. The crash manifests as SIGSEGV in `ff_tx_init_subtx` or similar
deep-FFmpeg init functions.

### Non-goals

- This invariant does NOT serialize steady-state decode/encode. That would
  violate INV-SEAM-001 (clock isolation) by blocking the tick thread on
  decoder I/O.
- This invariant does NOT prevent concurrent decode on separate contexts
  after initialization completes.

### Evidence

```
[INV-FFMPEG-CODEC-INIT-SERIALIZATION-001] guard_acquired thread=<thread_id>
[INV-FFMPEG-CODEC-INIT-SERIALIZATION-001] guard_released thread=<thread_id> held_ms=<N>
```

### Violation

SIGSEGV or data corruption during FFmpeg codec initialization when multiple
threads call `avcodec_open2` / `avformat_find_stream_info` concurrently.

---

## INV-FFMPEG-GLOBAL-INIT-001: Process-Level FFmpeg Initialization

### Statement

**`avformat_network_init()` MUST be called in `main()` before any threads are
spawned or any FFmpeg API is used.**

This initializes FFmpeg's global state (TLS/SSL libraries, network subsystem)
in a thread-safe manner before concurrent use begins.

### Rationale

FFmpeg's network subsystem (used by `avformat_open_input` for network-protocol
URIs such as `http://`, `rtmp://`, etc.) relies on global TLS/SSL initialization.
If this initialization races with concurrent FFmpeg calls, TLS handshakes can
crash or silently fail. `avformat_network_init()` is reference-counted and
idempotent, but MUST be called at least once before any network-dependent API.

### Owner

`main.cpp` — called in `main()` after signal handlers, before `ParseArgs`/`RunServer`.

### Test Mapping

| Test ID | File | What it proves |
|---------|------|----------------|
| T-FFMPEG-GLOBAL-INIT-001 | `FFmpegCodecInitSerializationTests.cpp` | `avformat_network_init()` succeeds and is idempotent |
| T-FFMPEG-GLOBAL-INIT-002 | `FFmpegCodecInitSerializationTests.cpp` | After global init, `avformat_open_input` can open local files (basic smoke) |

### Evidence

```
[INV-FFMPEG-GLOBAL-INIT-001] avformat_network_init called
```

### Violation

FFmpeg network I/O crashes or hangs on TLS handshake when opening network URIs,
due to uninitialized global state.
