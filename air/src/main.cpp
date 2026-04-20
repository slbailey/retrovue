// AIR vNext — minimal runnable binary.
//
// First binary milestone: accept one TCP client, stream SampleA through the
// proven pipeline (FileSourceProducer → StandardNormalizer → MpegTsEncoder →
// SocketEmitter) until EOF, clean shutdown.
//
// Usage:
//   retrovue_air_vnext --input /path/to/file.mp4 --listen <port>
//
// Test with ffplay:
//   retrovue_air_vnext --input SampleA.mp4 --listen 50100 &
//   ffplay tcp://127.0.0.1:50100
//
// Channel canonical is hardcoded to the "cheers" preset (968x720 @ 30000/1001,
// 48kHz stereo). No egress pacing yet — encoder emits as-fast-as-possible;
// ffplay buffers and plays back in real time. Real-time egress is slice #2.

#include <arpa/inet.h>
#include <netinet/in.h>
#include <signal.h>
#include <sys/socket.h>
#include <unistd.h>

#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <iostream>
#include <string>

#include "channel_canonical.hpp"
#include "egress_pacer.hpp"
#include "file_source_producer.hpp"
#include "mpeg_ts_encoder.hpp"
#include "socket_emitter.hpp"
#include "standard_normalizer.hpp"

namespace {

void Usage(const char* argv0) {
  std::fprintf(stderr,
               "usage: %s --input <file> --listen <port>\n"
               "  --input   path to input media (MP4 with H.264 + AAC)\n"
               "  --listen  TCP port to listen on (127.0.0.1)\n",
               argv0);
}

}  // namespace

int main(int argc, char** argv) {
  using namespace retrovue::air;

  std::string input_path;
  int listen_port = 0;

  for (int i = 1; i < argc; ++i) {
    if (std::strcmp(argv[i], "--input") == 0 && i + 1 < argc) {
      input_path = argv[++i];
    } else if (std::strcmp(argv[i], "--listen") == 0 && i + 1 < argc) {
      listen_port = std::atoi(argv[++i]);
    } else {
      Usage(argv[0]);
      return 2;
    }
  }
  if (input_path.empty() || listen_port <= 0 || listen_port > 65535) {
    Usage(argv[0]);
    return 2;
  }

  // SIGPIPE: never kill on consumer disconnect. MSG_NOSIGNAL in SocketEmitter
  // handles send() paths; this guards anything else.
  ::signal(SIGPIPE, SIG_IGN);

  // Bind + listen on 127.0.0.1:<port>.
  int listen_fd = ::socket(AF_INET, SOCK_STREAM, 0);
  if (listen_fd < 0) { std::perror("socket"); return 1; }

  int one = 1;
  ::setsockopt(listen_fd, SOL_SOCKET, SO_REUSEADDR, &one, sizeof(one));

  sockaddr_in addr{};
  addr.sin_family = AF_INET;
  addr.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
  addr.sin_port = htons(static_cast<uint16_t>(listen_port));
  if (::bind(listen_fd, reinterpret_cast<sockaddr*>(&addr), sizeof(addr)) < 0) {
    std::perror("bind");
    ::close(listen_fd);
    return 1;
  }
  if (::listen(listen_fd, 1) < 0) {
    std::perror("listen");
    ::close(listen_fd);
    return 1;
  }

  std::cerr << "[air] listening on tcp://127.0.0.1:" << listen_port
            << " — waiting for one client" << std::endl;

  int client_fd = ::accept(listen_fd, nullptr, nullptr);
  if (client_fd < 0) {
    std::perror("accept");
    ::close(listen_fd);
    return 1;
  }
  std::cerr << "[air] client connected; starting pipeline" << std::endl;

  // Pipeline setup (cheers preset — matches tests).
  const ChannelCanonical canonical{
      .video = VideoCanonical{.width = 968,
                              .height = 720,
                              .frame_rate = {30000, 1001},
                              .pixel_format = PixelFormat::kYuv420p},
      .audio = AudioCanonical{.sample_rate = 48000, .channels = 2}};

  FileSourceProducer src({.file_path = input_path});
  if (!src.Prepare()) {
    std::cerr << "[air] FileSourceProducer::Prepare failed for " << input_path
              << std::endl;
    ::close(client_fd);
    ::close(listen_fd);
    return 1;
  }
  if (!src.Activate()) {
    std::cerr << "[air] FileSourceProducer::Activate failed" << std::endl;
    ::close(client_fd);
    ::close(listen_fd);
    return 1;
  }

  const int audio_samples_per_block = 1601;
  StandardNormalizer norm(canonical, src.VideoFrameRate(),
                          src.VideoWidth(), src.VideoHeight(),
                          src.AudioSampleRate(), &src,
                          {.source_pts_anchor_us = 0,
                           .channel_pts_anchor_us = 0},
                          audio_samples_per_block);

  SocketEmitter emitter(client_fd);
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
  if (!encoder.Open(cfg, [&emitter](const uint8_t* buf, int n) {
        return emitter.Write(buf, n);
      })) {
    std::cerr << "[air] encoder.Open failed" << std::endl;
    ::close(client_fd);
    ::close(listen_fd);
    return 1;
  }

  // Real-time egress pacer: holds each video frame until its wall-clock
  // moment. Audio rides alongside video — one pacer gate controls the loop
  // cadence and the encoder/socket emit in lockstep with the channel clock.
  EgressPacer pacer;

  // Encode until the source runs out.
  int64_t frames = 0;
  while (true) {
    auto vf = norm.PullVideo();
    if (!vf.has_value()) break;
    pacer.WaitFor(vf->pts_us_relative);
    if (!encoder.EncodeVideo(*vf)) {
      std::cerr << "[air] EncodeVideo failed at frame " << frames << std::endl;
      break;
    }
    ++frames;
    auto ab = norm.PullAudio();
    if (ab.has_value()) encoder.EncodeAudio(*ab);
  }
  // Drain any leftover audio.
  for (int extra = 0; extra < 10; ++extra) {
    auto ab = norm.PullAudio();
    if (!ab.has_value()) break;
    encoder.EncodeAudio(*ab);
  }

  encoder.Flush();
  encoder.Close();
  src.Retire();

  std::cerr << "[air] done. frames=" << frames
            << " bytes_written=" << emitter.BytesWrittenTotal()
            << " bytes_dropped=" << emitter.BytesDroppedTotal()
            << " epipe=" << emitter.EpipeCount()
            << " pacer_total_sleep_ms=" << (pacer.TotalSleepUs() / 1000)
            << " pacer_late_releases=" << pacer.LateReleases() << std::endl;

  ::close(client_fd);
  ::close(listen_fd);
  return 0;
}
