// AIR vNext — SocketEmitter.
//
// Thin byte-out adapter that writes MpegTsEncoder output to a socket fd.
// Matches the encoder's BytesOutCallback shape via the Write() method.
//
// Product rule: AIR never throttles or detaches in response to downstream
// backpressure. If the socket is full (EAGAIN), bytes are dropped and the
// drop count is incremented. SIGPIPE is suppressed via MSG_NOSIGNAL; EPIPE
// on the consumer side increments the epipe counter and drops the bytes.
// The encoder is always told "all bytes written" regardless of what actually
// made it onto the wire — the pipeline never pauses.
//
// Caller owns the fd: open, configure, close. SocketEmitter does not take
// ownership. O_NONBLOCK is not required — every send() is tagged with
// MSG_DONTWAIT so blocking is impossible regardless of fd state.
//
// Vault references:
//   - AIR_Boundary INV-AIR-EMIT-UNCONDITIONAL-001
//   - Product decisions (memory): never-throttle, drop-on-full.

#ifndef AIR_SOCKET_EMITTER_HPP_
#define AIR_SOCKET_EMITTER_HPP_

#include <cstdint>

namespace retrovue::air {

class SocketEmitter {
 public:
  // Construct with an fd owned by the caller. The fd may be any SOCK_STREAM
  // socket (UDS, TCP, socketpair). A negative fd is a valid "no destination"
  // state — all writes are dropped silently.
  explicit SocketEmitter(int fd);
  ~SocketEmitter();

  SocketEmitter(const SocketEmitter&) = delete;
  SocketEmitter& operator=(const SocketEmitter&) = delete;

  // Write bytes to the fd. Always returns buf_size (never partial).
  // Matches MpegTsEncoder's BytesOutCallback signature.
  int Write(const uint8_t* buf, int buf_size);

  // Diagnostics (post-run inspection; not for control-flow decisions).
  int64_t BytesWrittenTotal() const { return bytes_written_; }
  int64_t BytesDroppedTotal() const { return bytes_dropped_; }
  int64_t EpipeCount() const { return epipe_count_; }

 private:
  int fd_;
  int64_t bytes_written_{0};
  int64_t bytes_dropped_{0};
  int64_t epipe_count_{0};
};

}  // namespace retrovue::air

#endif  // AIR_SOCKET_EMITTER_HPP_
