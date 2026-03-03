// Repository: Retrovue-playout
// Component: FFmpegInitGuard
// Purpose: Process-wide mutex serializing all FFmpeg codec initialization
//          (avformat_open_input, avformat_find_stream_info, avcodec_open2)
//          across threads.
//          Steady-state decode/encode on separate AVCodecContext instances
//          is safe without this guard.
// Contract Reference: INV-FFMPEG-CODEC-INIT-SERIALIZATION-001
// Copyright (c) 2025 RetroVue

#ifndef RETROVUE_DECODE_FFMPEG_INIT_GUARD_HPP_
#define RETROVUE_DECODE_FFMPEG_INIT_GUARD_HPP_

#include <mutex>

namespace retrovue::decode {

// Returns the process-wide mutex that must be held during all FFmpeg codec
// initialization calls (avformat_open_input, avformat_find_stream_info,
// avcodec_open2).
//
// Usage:
//   {
//     std::lock_guard<std::mutex> guard(retrovue::decode::ffmpeg_init_mutex());
//     avformat_open_input(&fmt_ctx, uri, nullptr, nullptr);
//     avformat_find_stream_info(fmt_ctx, nullptr);
//     avcodec_open2(codec_ctx, codec, nullptr);
//   }
//   // steady-state decode can proceed without the guard
//
// Thread safety: The returned reference is stable for the process lifetime
// (Meyer's singleton). The mutex itself provides serialization.
//
// WARNING: This is a non-recursive std::mutex. Do NOT acquire it recursively
// (e.g. do not call ProbeAsset() from within an already-guarded Open() path).
// All current call sites acquire the guard at the outermost init entry point
// and hold it through sub-calls (InitializeCodec, InitializeAudioCodec, etc.).
inline std::mutex& ffmpeg_init_mutex() {
  static std::mutex mtx;
  return mtx;
}

}  // namespace retrovue::decode

#endif  // RETROVUE_DECODE_FFMPEG_INIT_GUARD_HPP_
