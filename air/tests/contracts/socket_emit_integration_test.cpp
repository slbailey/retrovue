// AIR vNext — SocketEmitter integration test.
//
// Proves the full byte path leaves AIR via a real socket:
//   FileSourceProducer(SampleA)
//     -> StandardNormalizer (channel canonical 968x720 @ 30000/1001, 48kHz stereo)
//       -> MpegTsEncoder
//         -> SocketEmitter(writer fd of socketpair)
//           -> [wire]
//             -> reader thread drains into std::vector
//               -> ffprobe validates stream.
//
// This is the first-bytes-on-wire milestone for AIR vNext.

#include <gtest/gtest.h>

#include <sys/socket.h>
#include <unistd.h>

#include <array>
#include <atomic>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <string>
#include <thread>
#include <vector>

#include "channel_canonical.hpp"
#include "file_source_producer.hpp"
#include "mpeg_ts_encoder.hpp"
#include "socket_emitter.hpp"
#include "standard_normalizer.hpp"

namespace retrovue::air {
namespace {

std::string ResolveSampleA() {
  if (const char* env = std::getenv("AIR_VNEXT_TEST_MEDIA")) {
    return std::string(env);
  }
#ifdef AIR_VNEXT_SAMPLE_A_PATH
  return std::string(AIR_VNEXT_SAMPLE_A_PATH);
#else
  return "";
#endif
}

bool FixtureExists(const std::string& path) {
  std::ifstream f(path);
  return f.good();
}

ChannelCanonical CheersChannelCanonical() {
  return ChannelCanonical{
      .video = VideoCanonical{.width = 968,
                              .height = 720,
                              .frame_rate = {30000, 1001},
                              .pixel_format = PixelFormat::kYuv420p},
      .audio = AudioCanonical{.sample_rate = 48000, .channels = 2}};
}

struct FFProbeResult {
  int exit_code;
  std::string output;
};

FFProbeResult RunFFProbeOnBytes(const std::vector<uint8_t>& bytes) {
  char tmpl[] = "/tmp/air_socket_emit_XXXXXX.ts";
  int fd = mkstemps(tmpl, 3);
  if (fd < 0) return {-1, "mkstemps failed"};
  FILE* f = fdopen(fd, "wb");
  if (!f) {
    close(fd);
    std::remove(tmpl);
    return {-1, "fdopen failed"};
  }
  const size_t written = std::fwrite(bytes.data(), 1, bytes.size(), f);
  std::fclose(f);
  if (written != bytes.size()) {
    std::remove(tmpl);
    return {-1, "fwrite short"};
  }

  std::string cmd =
      "ffprobe -v error -show_streams -print_format default ";
  cmd += tmpl;
  cmd += " 2>&1";
  FILE* pipe = popen(cmd.c_str(), "r");
  if (!pipe) {
    std::remove(tmpl);
    return {-1, "popen failed"};
  }
  std::string out;
  std::array<char, 4096> buf{};
  while (size_t n = std::fread(buf.data(), 1, buf.size(), pipe)) {
    out.append(buf.data(), n);
  }
  int status = pclose(pipe);
  std::remove(tmpl);
  int exit_code = WIFEXITED(status) ? WEXITSTATUS(status) : -1;
  return {exit_code, out};
}

TEST(SocketEmitIntegrationTest, SampleAReachesSocketAsValidMpegTs) {
  const std::string path = ResolveSampleA();
  if (!FixtureExists(path)) {
    GTEST_SKIP() << "SampleA not found at " << path;
  }

  // Create a local stream socketpair. fds[0] = reader, fds[1] = writer.
  int fds[2];
  ASSERT_EQ(socketpair(AF_UNIX, SOCK_STREAM, 0, fds), 0)
      << "socketpair failed: " << std::strerror(errno);

  const int reader_fd = fds[0];
  const int writer_fd = fds[1];

  // Reader thread: drain the socket until EOF, accumulate bytes.
  std::vector<uint8_t> received;
  received.reserve(2 * 1024 * 1024);
  std::atomic<bool> reader_done{false};
  std::thread reader([&]() {
    std::array<uint8_t, 64 * 1024> buf{};
    for (;;) {
      ssize_t n = ::read(reader_fd, buf.data(), buf.size());
      if (n > 0) {
        received.insert(received.end(), buf.data(), buf.data() + n);
        continue;
      }
      if (n == 0) break;  // EOF: writer closed
      if (n < 0) {
        if (errno == EINTR) continue;
        break;  // terminal error
      }
    }
    reader_done = true;
  });

  // Pipeline setup.
  const ChannelCanonical canonical = CheersChannelCanonical();

  FileSourceProducer src({.file_path = path});
  ASSERT_TRUE(src.Prepare());
  ASSERT_TRUE(src.Activate());

  const int audio_samples_per_block = 1601;
  StandardNormalizer norm(canonical, src.VideoFrameRate(),
                          src.VideoWidth(), src.VideoHeight(),
                          src.AudioSampleRate(), &src,
                          {.source_pts_anchor_us = 0,
                           .channel_pts_anchor_us = 0},
                          audio_samples_per_block);

  // Emitter wires encoder bytes to the writer fd.
  SocketEmitter emitter(writer_fd);

  MpegTsEncoder encoder;
  MpegTsEncoderConfig cfg{
      .video_width = canonical.video.width,
      .video_height = canonical.video.height,
      .video_fps_num = static_cast<int>(canonical.video.frame_rate.num),
      .video_fps_den = static_cast<int>(canonical.video.frame_rate.den),
      .video_bitrate_bps = 4'000'000,
      .audio_sample_rate = canonical.audio.sample_rate,
      .audio_channels = canonical.audio.channels,
      .audio_bitrate_bps = 192'000,
  };
  ASSERT_TRUE(encoder.Open(cfg, [&emitter](const uint8_t* buf, int buf_size) {
    return emitter.Write(buf, buf_size);
  }));

  // Encode ~60 frames, interleaving audio per video.
  const int kTargetFrames = 60;
  int pulled_video = 0;
  int pulled_audio = 0;
  for (int k = 0; k < kTargetFrames; ++k) {
    auto vf = norm.PullVideo();
    if (!vf.has_value()) break;
    ASSERT_TRUE(encoder.EncodeVideo(*vf)) << "EncodeVideo failed at k=" << k;
    ++pulled_video;

    auto ab = norm.PullAudio();
    if (ab.has_value()) {
      ASSERT_TRUE(encoder.EncodeAudio(*ab)) << "EncodeAudio failed at k=" << k;
      ++pulled_audio;
    }
  }
  // Drain a few extra audio blocks so the interleaver has enough audio.
  for (int extra = 0; extra < 5; ++extra) {
    auto ab = norm.PullAudio();
    if (!ab.has_value()) break;
    ASSERT_TRUE(encoder.EncodeAudio(*ab));
    ++pulled_audio;
  }

  encoder.Flush();
  encoder.Close();
  src.Retire();

  // Deterministic shutdown: close writer end to signal EOF to reader.
  ASSERT_EQ(close(writer_fd), 0) << "close(writer_fd) failed: "
                                 << std::strerror(errno);
  reader.join();
  ASSERT_TRUE(reader_done.load());
  ASSERT_EQ(close(reader_fd), 0);

  // Assertions on what reached the wire.
  ASSERT_GT(pulled_video, 0);
  ASSERT_GT(pulled_audio, 0);
  ASSERT_GT(received.size(), 0u) << "no bytes reached the socket";

  // MPEG-TS sync byte at offset 0 and at least the next ~20 packet boundaries.
  ASSERT_EQ(received[0], 0x47)
      << "first received byte is not TS sync (0x47): got 0x"
      << std::hex << static_cast<int>(received[0]);
  const int kCheckPackets = 20;
  for (int p = 0; p < kCheckPackets &&
                  (p + 1) * 188 <= static_cast<int>(received.size());
       ++p) {
    ASSERT_EQ(received[p * 188], 0x47)
        << "received packet " << p << " missing sync byte at offset "
        << (p * 188);
  }

  // Diagnostics: for this test we expect zero drops on a local socketpair.
  EXPECT_EQ(emitter.BytesDroppedTotal(), 0)
      << "unexpected drops on local socketpair";
  EXPECT_EQ(emitter.EpipeCount(), 0);
  EXPECT_EQ(emitter.BytesWrittenTotal(),
            static_cast<int64_t>(received.size()))
      << "emitter-reported bytes != bytes received over socket";

  // ffprobe validation.
  auto probe = RunFFProbeOnBytes(received);
  EXPECT_EQ(probe.exit_code, 0)
      << "ffprobe exit=" << probe.exit_code << " output=" << probe.output;
  std::cout << "[ffprobe output]\n" << probe.output << std::endl;
  EXPECT_NE(probe.output.find("codec_type=video"), std::string::npos)
      << "ffprobe did not report a video stream: " << probe.output;
  EXPECT_NE(probe.output.find("codec_type=audio"), std::string::npos)
      << "ffprobe did not report an audio stream: " << probe.output;
}

}  // namespace
}  // namespace retrovue::air
