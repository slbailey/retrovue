// AIR vNext — preview BufferStore implementations.

#include "preview_buffer.hpp"

namespace retrovue::air {

bool VideoPreviewBuffer::Push(VideoFrame frame) {
  if (static_cast<int>(frames_.size()) >= capacity_) {
    ++obs_.overflow_count;
    return false;
  }
  frames_.push_back(std::move(frame));
  ++obs_.total_pushed;
  return true;
}

std::optional<VideoFrame> VideoPreviewBuffer::Pop() {
  if (frames_.empty()) {
    ++obs_.underflow_count;
    return std::nullopt;
  }
  VideoFrame front = std::move(frames_.front());
  frames_.pop_front();
  ++obs_.total_popped;
  return front;
}

std::optional<int64_t> VideoPreviewBuffer::FrontPtsUsRelative() const {
  if (frames_.empty()) return std::nullopt;
  return frames_.front().pts_us_relative;
}

std::optional<int64_t> VideoPreviewBuffer::BackPtsUsRelative() const {
  if (frames_.empty()) return std::nullopt;
  return frames_.back().pts_us_relative;
}

bool AudioPreviewBuffer::Push(AudioBlock block) {
  if (static_cast<int>(blocks_.size()) >= capacity_) {
    ++obs_.overflow_count;
    return false;
  }
  blocks_.push_back(std::move(block));
  ++obs_.total_pushed;
  return true;
}

std::optional<AudioBlock> AudioPreviewBuffer::Pop() {
  if (blocks_.empty()) {
    ++obs_.underflow_count;
    return std::nullopt;
  }
  AudioBlock front = std::move(blocks_.front());
  blocks_.pop_front();
  ++obs_.total_popped;
  return front;
}

std::optional<int64_t> AudioPreviewBuffer::FrontPtsUsRelative() const {
  if (blocks_.empty()) return std::nullopt;
  return blocks_.front().pts_us_relative;
}

std::optional<int64_t> AudioPreviewBuffer::BackPtsUsRelative() const {
  if (blocks_.empty()) return std::nullopt;
  return blocks_.back().pts_us_relative;
}

}  // namespace retrovue::air
