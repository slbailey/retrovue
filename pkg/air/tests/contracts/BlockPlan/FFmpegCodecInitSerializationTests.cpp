// Repository: Retrovue-playout
// Component: FFmpeg Codec Init Serialization Contract Tests
// Purpose: Verify INV-FFMPEG-CODEC-INIT-SERIALIZATION-001
// Contract Reference: pkg/air/docs/contracts/semantics/FFmpegCodecInitSerializationContract.md
// Copyright (c) 2025 RetroVue
//
// Tests:
//   T-FFMPEG-INIT-001: GuardSerializesConcurrentProbe
//     Outcome: INV-FFMPEG-CODEC-INIT-SERIALIZATION-001
//     Verify: Multiple threads calling RealAssetSource::ProbeAsset concurrently
//             do not crash. The ffmpeg_init_mutex serializes avformat_find_stream_info.
//     Method: Launch N threads each probing a media file. Without serialization,
//             this races on FFmpeg global state (AAC SBR tables, FFT codelets).
//             With the guard, all probes complete without SIGSEGV.
//     Assertions:
//       - All threads complete without crash
//       - All probes return valid results
//
//   T-FFMPEG-INIT-002: GuardSerializesConcurrentDecoderOpen
//     Outcome: INV-FFMPEG-CODEC-INIT-SERIALIZATION-001
//     Verify: Multiple threads opening FFmpegDecoder concurrently complete
//             without crash. The init guard serializes avcodec_open2.
//     Method: Launch N threads each opening a decoder on a media file.
//     Assertions:
//       - All threads complete without crash
//       - All decoders open successfully
//
//   T-FFMPEG-INIT-003: GuardDoesNotBlockSteadyStateDecode
//     Outcome: INV-FFMPEG-CODEC-INIT-SERIALIZATION-001 (non-goal verification)
//     Verify: After initialization, steady-state decode does not acquire the
//             init guard. Concurrent decode on separate contexts proceeds
//             without serialization.
//     Method: Open two decoders (serialized via guard). Then decode frames
//             concurrently on both. Verify no contention on the init mutex
//             during steady-state.
//     Assertions:
//       - Both decoders produce frames concurrently
//       - Init mutex is not held during DecodeFrameToBuffer
//
//   T-FFMPEG-GLOBAL-INIT-001: NetworkInitSucceedsAndIsIdempotent
//     Outcome: INV-FFMPEG-GLOBAL-INIT-001
//     Verify: avformat_network_init() returns 0 and is idempotent.
//     Assertions:
//       - Two consecutive calls both return 0
//
//   T-FFMPEG-GLOBAL-INIT-002: OpenInputWorksAfterGlobalInit
//     Outcome: INV-FFMPEG-GLOBAL-INIT-001
//     Verify: After avformat_network_init(), avformat_open_input succeeds on
//             a local file (basic smoke test proving global state is ready).
//     Assertions:
//       - avformat_open_input returns >= 0

#include <gtest/gtest.h>

#include <atomic>
#include <thread>
#include <vector>

extern "C" {
#include <libavformat/avformat.h>
}

#include "retrovue/blockplan/RealAssetSource.hpp"
#include "retrovue/decode/FFmpegDecoder.h"
#include "retrovue/decode/FFmpegInitGuard.hpp"

namespace {

// Test media file — use the same asset from the crash log (a short commercial).
// Skip test if not available.
const char* kTestAsset1 =
    "/mnt/data/Interstitials/Commercials/"
    "1986-Pontiac-Firebird-Transam-Commercial-Rare-1-Minute-Version-720-"
    "Publer.Io00000125.mp4";

bool FileExists(const char* path) {
  return access(path, R_OK) == 0;
}

}  // namespace

// =============================================================================
// T-FFMPEG-INIT-001: Concurrent ProbeAsset with serialization guard
// =============================================================================

TEST(FFmpegCodecInitSerialization,
     T_FFMPEG_INIT_001_GuardSerializesConcurrentProbe) {
  if (!FileExists(kTestAsset1)) {
    GTEST_SKIP() << "Test asset not available: " << kTestAsset1;
  }

  constexpr int kNumThreads = 8;
  std::atomic<int> success_count{0};
  std::atomic<int> failure_count{0};

  std::vector<std::thread> threads;
  threads.reserve(kNumThreads);

  for (int i = 0; i < kNumThreads; ++i) {
    threads.emplace_back([&]() {
      // Each thread gets its own RealAssetSource (separate AVFormatContext).
      // The init guard inside ProbeAsset serializes avformat_find_stream_info.
      retrovue::blockplan::realtime::RealAssetSource source;
      bool ok = source.ProbeAsset(kTestAsset1);
      if (ok) {
        success_count.fetch_add(1, std::memory_order_relaxed);
      } else {
        failure_count.fetch_add(1, std::memory_order_relaxed);
      }
    });
  }

  for (auto& t : threads) {
    t.join();
  }

  // If we reach here, no SIGSEGV. That's the primary assertion.
  // All probes should also succeed (valid file).
  EXPECT_EQ(success_count.load(), kNumThreads)
      << "All concurrent probes should succeed";
  EXPECT_EQ(failure_count.load(), 0);
}

// =============================================================================
// T-FFMPEG-INIT-002: Concurrent FFmpegDecoder::Open with serialization guard
// =============================================================================

TEST(FFmpegCodecInitSerialization,
     T_FFMPEG_INIT_002_GuardSerializesConcurrentDecoderOpen) {
  if (!FileExists(kTestAsset1)) {
    GTEST_SKIP() << "Test asset not available: " << kTestAsset1;
  }

  constexpr int kNumThreads = 8;
  std::atomic<int> success_count{0};
  std::atomic<int> failure_count{0};

  std::vector<std::thread> threads;
  threads.reserve(kNumThreads);

  for (int i = 0; i < kNumThreads; ++i) {
    threads.emplace_back([&]() {
      retrovue::decode::DecoderConfig config;
      config.input_uri = kTestAsset1;
      config.target_width = 968;
      config.target_height = 720;
      retrovue::decode::FFmpegDecoder decoder(config);
      bool ok = decoder.Open();
      if (ok) {
        success_count.fetch_add(1, std::memory_order_relaxed);
        // Decode a few frames to exercise steady-state path
        retrovue::buffer::Frame frame;
        for (int f = 0; f < 5; ++f) {
          decoder.DecodeFrameToBuffer(frame);
        }
        decoder.Close();
      } else {
        failure_count.fetch_add(1, std::memory_order_relaxed);
      }
    });
  }

  for (auto& t : threads) {
    t.join();
  }

  EXPECT_EQ(success_count.load(), kNumThreads)
      << "All concurrent decoder opens should succeed";
  EXPECT_EQ(failure_count.load(), 0);
}

// =============================================================================
// T-FFMPEG-INIT-003: Steady-state decode does not hold init mutex
// =============================================================================

TEST(FFmpegCodecInitSerialization,
     T_FFMPEG_INIT_003_GuardDoesNotBlockSteadyStateDecode) {
  if (!FileExists(kTestAsset1)) {
    GTEST_SKIP() << "Test asset not available: " << kTestAsset1;
  }

  // Open two decoders sequentially (serialized by guard).
  retrovue::decode::DecoderConfig config;
  config.input_uri = kTestAsset1;
  config.target_width = 968;
  config.target_height = 720;

  retrovue::decode::FFmpegDecoder decoder1(config);
  retrovue::decode::FFmpegDecoder decoder2(config);
  ASSERT_TRUE(decoder1.Open());
  ASSERT_TRUE(decoder2.Open());

  // Now decode concurrently on both — steady state, no init guard needed.
  constexpr int kFrames = 30;
  std::atomic<int> frames1{0};
  std::atomic<int> frames2{0};

  std::thread t1([&]() {
    retrovue::buffer::Frame frame;
    for (int i = 0; i < kFrames; ++i) {
      if (decoder1.DecodeFrameToBuffer(frame)) {
        frames1.fetch_add(1, std::memory_order_relaxed);
      }
    }
  });

  std::thread t2([&]() {
    retrovue::buffer::Frame frame;
    for (int i = 0; i < kFrames; ++i) {
      if (decoder2.DecodeFrameToBuffer(frame)) {
        frames2.fetch_add(1, std::memory_order_relaxed);
      }
    }
  });

  // While decoding is running, verify the init mutex is NOT held.
  // try_lock should succeed (nobody holds it during steady-state decode).
  std::this_thread::sleep_for(std::chrono::milliseconds(10));
  bool mutex_free = retrovue::decode::ffmpeg_init_mutex().try_lock();
  if (mutex_free) {
    retrovue::decode::ffmpeg_init_mutex().unlock();
  }

  t1.join();
  t2.join();

  EXPECT_TRUE(mutex_free)
      << "Init mutex should not be held during steady-state decode";
  EXPECT_GT(frames1.load(), 0) << "Decoder 1 should produce frames";
  EXPECT_GT(frames2.load(), 0) << "Decoder 2 should produce frames";

  decoder1.Close();
  decoder2.Close();
}

// =============================================================================
// T-FFMPEG-GLOBAL-INIT-001: avformat_network_init succeeds and is idempotent
// =============================================================================

TEST(FFmpegGlobalInit,
     T_FFMPEG_GLOBAL_INIT_001_NetworkInitSucceedsAndIsIdempotent) {
  // avformat_network_init is reference-counted. Calling it multiple times must
  // succeed (return 0) without error — proving idempotency.
  // In production, main() calls this once before threads spawn.
  int ret1 = avformat_network_init();
  EXPECT_EQ(ret1, 0) << "First avformat_network_init should succeed";

  int ret2 = avformat_network_init();
  EXPECT_EQ(ret2, 0) << "Second avformat_network_init should succeed (idempotent)";

  // Balance the reference count.
  avformat_network_deinit();
  avformat_network_deinit();
}

// =============================================================================
// T-FFMPEG-GLOBAL-INIT-002: After global init, avformat_open_input works
// =============================================================================

TEST(FFmpegGlobalInit,
     T_FFMPEG_GLOBAL_INIT_002_OpenInputWorksAfterGlobalInit) {
  if (!FileExists(kTestAsset1)) {
    GTEST_SKIP() << "Test asset not available: " << kTestAsset1;
  }

  // Ensure global init is done (gtest_main does not call it; production main does).
  avformat_network_init();

  AVFormatContext* fmt_ctx = nullptr;
  int ret = avformat_open_input(&fmt_ctx, kTestAsset1, nullptr, nullptr);
  EXPECT_GE(ret, 0) << "avformat_open_input should succeed after global init";

  if (fmt_ctx) {
    avformat_close_input(&fmt_ctx);
  }

  avformat_network_deinit();
}
