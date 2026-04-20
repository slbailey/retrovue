// AIR vNext — SocketEmitter implementation.

#include "socket_emitter.hpp"

#include <errno.h>
#include <sys/socket.h>

namespace retrovue::air {

SocketEmitter::SocketEmitter(int fd) : fd_(fd) {}

SocketEmitter::~SocketEmitter() = default;

int SocketEmitter::Write(const uint8_t* buf, int buf_size) {
  if (buf_size <= 0) return buf_size;
  if (fd_ < 0) {
    bytes_dropped_ += buf_size;
    return buf_size;
  }

  int written = 0;
  while (written < buf_size) {
    // MSG_NOSIGNAL: suppress SIGPIPE on a closed peer — we handle EPIPE below.
    // MSG_DONTWAIT: never block regardless of fd's O_NONBLOCK state.
    ssize_t n = ::send(fd_, buf + written, buf_size - written,
                       MSG_NOSIGNAL | MSG_DONTWAIT);
    if (n > 0) {
      written += static_cast<int>(n);
      bytes_written_ += n;
      continue;
    }
    if (n < 0) {
      if (errno == EINTR) continue;
      if (errno == EAGAIN || errno == EWOULDBLOCK) {
        // Socket full. Product rule: never throttle. Drop remainder, return.
        bytes_dropped_ += (buf_size - written);
        return buf_size;
      }
      if (errno == EPIPE || errno == ECONNRESET) {
        // Consumer disconnected. Record and continue — pipeline never stalls.
        ++epipe_count_;
        bytes_dropped_ += (buf_size - written);
        return buf_size;
      }
      // Any other error: drop and continue.
      bytes_dropped_ += (buf_size - written);
      return buf_size;
    }
    // n == 0: treat as peer gone.
    bytes_dropped_ += (buf_size - written);
    return buf_size;
  }
  return buf_size;
}

}  // namespace retrovue::air
