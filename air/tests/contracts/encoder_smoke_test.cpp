// AIR vNext — MpegTsEncoder smoke test.
//
// End-to-end: FileSourceProducer(SampleA) -> StandardNormalizer (channel
// canonical 968x720 @ 30000/1001, 48kHz stereo) -> MpegTsEncoder ->
// std::vector<uint8_t>. Then pipe the bytes through ffprobe to prove the
// stream is structurally valid MPEG-TS with decodable streams.

#include <gtest/gtest.h>

#include <array>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <optional>
#include <string>
#include <vector>

#include "channel_canonical.hpp"
#include "file_source_producer.hpp"
#include "mpeg_ts_encoder.hpp"
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

// Pipe the provided MPEG-TS bytes to ffprobe via stdin. Return (exit_code,
// combined_stdout_stderr). Using popen with a write pipe, then reading back
// via a tmp file is clunky; instead we write bytes to a tmp file and read
// ffprobe output via a read pipe. This avoids needing a bidirectional popen.
struct FFProbeResult {
  int exit_code;
  std::string output;
};

FFProbeResult RunFFProbeOnBytes(const std::vector<uint8_t>& bytes) {
  // Write bytes to a tmp file.
  char tmpl[] = "/tmp/air_encoder_smoke_XXXXXX.ts";
  int fd = mkstemps(tmpl, 3);
  if (fd < 0) {
    return {-1, "mkstemps failed"};
  }
  FILE* f = fdopen(fd, "wb");
  if (!f) {
    close(fd);
    std::remove(tmpl);
    return {-1, "fdopen failed"};
  }
  size_t written = std::fwrite(bytes.data(), 1, bytes.size(), f);
  std::fclose(f);
  if (written != bytes.size()) {
    std::remove(tmpl);
    return {-1, "fwrite short"};
  }

  // Run ffprobe.
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

TEST(EncoderSmokeTest, SampleADecodedEncodedValidMpegTs) {
  const std::string path = ResolveSampleA();
  if (!FixtureExists(path)) {
    GTEST_SKIP() << "SampleA not found at " << path;
  }

  const ChannelCanonical canonical = CheersChannelCanonical();

  FileSourceProducer src({.file_path = path});
  ASSERT_TRUE(src.Prepare());
  ASSERT_TRUE(src.Activate());

  // Channel audio block: ~ one video-frame-period of samples at 48kHz.
  // For 30000/1001, a frame is ~1601 samples (same as file_decode_test).
  const int audio_samples_per_block = 1601;

  StandardNormalizer norm(canonical, src.VideoFrameRate(),
                          src.VideoWidth(), src.VideoHeight(),
                          src.AudioSampleRate(), &src,
                          {.source_pts_anchor_us = 0,
                           .channel_pts_anchor_us = 0},
                          audio_samples_per_block);

  std::vector<uint8_t> output;
  output.reserve(2 * 1024 * 1024);

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
  ASSERT_TRUE(encoder.Open(cfg, [&output](const uint8_t* buf, int buf_size) {
    output.insert(output.end(), buf, buf + buf_size);
    return buf_size;
  }));

  // Pull ~60 video frames; for each frame, also pull ~one channel-frame's
  // worth of audio so the interleaver sees both streams.
  const int kTargetFrames = 60;
  int pulled_video = 0;
  int pulled_audio = 0;
  for (int k = 0; k < kTargetFrames; ++k) {
    auto vf = norm.PullVideo();
    if (!vf.has_value()) break;
    ASSERT_TRUE(encoder.EncodeVideo(*vf)) << "EncodeVideo failed at k=" << k;
    ++pulled_video;

    // Interleave an audio block per video frame (roughly matched cadence).
    auto ab = norm.PullAudio();
    if (ab.has_value()) {
      ASSERT_TRUE(encoder.EncodeAudio(*ab)) << "EncodeAudio failed at k=" << k;
      ++pulled_audio;
    }
  }

  // Drain any extra audio blocks that may be available to ensure the
  // interleaver has sufficient audio to cover the video span on final flush.
  for (int extra = 0; extra < 5; ++extra) {
    auto ab = norm.PullAudio();
    if (!ab.has_value()) break;
    ASSERT_TRUE(encoder.EncodeAudio(*ab));
    ++pulled_audio;
  }

  encoder.Flush();
  encoder.Close();

  ASSERT_GT(pulled_video, 0);
  ASSERT_GT(pulled_audio, 0);
  ASSERT_GT(output.size(), 0u) << "no TS bytes emitted";

  // MPEG-TS sync byte check: 0x47 at byte 0 and every 188 bytes.
  ASSERT_EQ(output[0], 0x47) << "first byte is not TS sync";
  const int kCheckPackets = 20;
  for (int p = 0; p < kCheckPackets && (p + 1) * 188 <= static_cast<int>(output.size()); ++p) {
    ASSERT_EQ(output[p * 188], 0x47)
        << "packet " << p << " missing sync byte at offset " << (p * 188);
  }

  // ffprobe validation.
  auto probe = RunFFProbeOnBytes(output);
  EXPECT_EQ(probe.exit_code, 0)
      << "ffprobe exit=" << probe.exit_code << " output=" << probe.output;
  // Print stream info for proof in the test log.
  std::cout << "[ffprobe output]\n" << probe.output << std::endl;
  // Structural checks on the ffprobe output.
  EXPECT_NE(probe.output.find("codec_type=video"), std::string::npos)
      << "ffprobe did not report a video stream: " << probe.output;
  EXPECT_NE(probe.output.find("codec_type=audio"), std::string::npos)
      << "ffprobe did not report an audio stream: " << probe.output;

  src.Retire();
}

}  // namespace
}  // namespace retrovue::air
