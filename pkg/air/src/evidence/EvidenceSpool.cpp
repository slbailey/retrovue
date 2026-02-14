// Repository: RetroVue
// Component: AIR evidence spool implementation
// Contract: pkg/air/docs/contracts/AirExecutionEvidenceSpoolContract_v0.1.md

#include "evidence/EvidenceSpool.hpp"
#include <cerrno>
#include <fstream>
#include <sstream>
#include <stdexcept>
#include <sys/stat.h>
#include <unistd.h>

namespace retrovue::evidence {

namespace {

std::string JsonEscape(const std::string& s) {
  std::string out;
  out.reserve(s.size() + 8);
  for (char c : s) {
    if (c == '"') out += "\\\"";
    else if (c == '\\') out += "\\\\";
    else if (c == '\n') out += "\\n";
    else if (c == '\r') out += "\\r";
    else if (c == '\t') out += "\\t";
    else out += c;
  }
  return out;
}

// Parse string value after key; assumes key is followed by ": and value in quotes.
// Returns true and sets out if found; advances *pos past the value.
bool ParseJsonStringValue(const std::string& line, const std::string& key,
                          size_t* pos, std::string* out) {
  std::string search = "\"" + key + "\":\"";
  size_t start = line.find(search, *pos);
  if (start == std::string::npos) return false;
  start += search.size();
  out->clear();
  for (size_t i = start; i < line.size(); ++i) {
    if (line[i] == '\\' && i + 1 < line.size()) {
      if (line[i + 1] == '"') { *out += '"'; i++; continue; }
      if (line[i + 1] == '\\') { *out += '\\'; i++; continue; }
      if (line[i + 1] == 'n')  { *out += '\n'; i++; continue; }
      if (line[i + 1] == 'r')  { *out += '\r'; i++; continue; }
      if (line[i + 1] == 't')  { *out += '\t'; i++; continue; }
    }
    if (line[i] == '"') {
      *pos = i + 1;
      return true;
    }
    *out += line[i];
  }
  return false;
}

bool ParseJsonUint64Value(const std::string& line, const std::string& key,
                          size_t* pos, uint64_t* out) {
  std::string search = "\"" + key + "\":";
  size_t start = line.find(search, *pos);
  if (start == std::string::npos) return false;
  start += search.size();
  size_t end = start;
  while (end < line.size() && (std::isdigit(static_cast<unsigned char>(line[end])) || line[end] == ' '))
    ++end;
  if (end == start) return false;
  try {
    *out = static_cast<uint64_t>(std::stoull(line.substr(start, end - start)));
    *pos = end;
    return true;
  } catch (...) {
    return false;
  }
}

bool ParseJsonUint32Value(const std::string& line, const std::string& key,
                          size_t* pos, uint32_t* out) {
  uint64_t v;
  if (!ParseJsonUint64Value(line, key, pos, &v)) return false;
  if (v > 0xFFFFFFFFu) return false;
  *out = static_cast<uint32_t>(v);
  return true;
}

// Extract value of "payload" as JSON object (substring from first { to matching }).
bool ParsePayloadObject(const std::string& line, size_t* pos, std::string* out) {
  size_t start = line.find("\"payload\":", *pos);
  if (start == std::string::npos) return false;
  start += 10;  // length of "payload":
  while (start < line.size() && (line[start] == ' ' || line[start] == '\t')) ++start;
  if (start >= line.size() || line[start] != '{') return false;
  size_t depth = 1;
  size_t i = start + 1;
  while (i < line.size() && depth > 0) {
    if (line[i] == '{') ++depth;
    else if (line[i] == '}') --depth;
    else if (line[i] == '"') {
      ++i;
      while (i < line.size() && (line[i] != '"' || (i > 0 && line[i-1] == '\\'))) ++i;
    }
    ++i;
  }
  if (depth != 0) return false;
  *out = line.substr(start, i - start);
  *pos = i;
  return true;
}

}  // namespace

std::string EvidenceFromAir::ToJsonLine() const {
  std::ostringstream o;
  o << "{\"schema_version\":" << schema_version
    << ",\"channel_id\":\"" << JsonEscape(channel_id) << "\""
    << ",\"playout_session_id\":\"" << JsonEscape(playout_session_id) << "\""
    << ",\"sequence\":" << sequence
    << ",\"event_uuid\":\"" << JsonEscape(event_uuid) << "\""
    << ",\"emitted_utc\":\"" << JsonEscape(emitted_utc) << "\""
    << ",\"payload_type\":\"" << JsonEscape(payload_type) << "\""
    << ",\"payload\":";
  if (payload.empty() || payload.front() != '{')
    o << "{}";
  else
    o << payload;
  o << "}";
  return o.str();
}

bool EvidenceFromAir::FromJsonLine(const std::string& line, EvidenceFromAir& out) {
  if (line.empty() || line.front() != '{' || line.back() != '}')
    return false;
  size_t pos = 0;
  if (!ParseJsonUint32Value(line, "schema_version", &pos, &out.schema_version)) return false;
  if (!ParseJsonStringValue(line, "channel_id", &pos, &out.channel_id)) return false;
  if (!ParseJsonStringValue(line, "playout_session_id", &pos, &out.playout_session_id)) return false;
  if (!ParseJsonUint64Value(line, "sequence", &pos, &out.sequence)) return false;
  if (!ParseJsonStringValue(line, "event_uuid", &pos, &out.event_uuid)) return false;
  if (!ParseJsonStringValue(line, "emitted_utc", &pos, &out.emitted_utc)) return false;
  if (!ParseJsonStringValue(line, "payload_type", &pos, &out.payload_type)) return false;
  if (!ParsePayloadObject(line, &pos, &out.payload)) return false;
  return true;
}

// -----------------------------------------------------------------------------
// EvidenceSpool
// -----------------------------------------------------------------------------

EvidenceSpool::EvidenceSpool(std::string channel_id,
                             std::string playout_session_id,
                             const std::string& spool_root,
                             size_t max_spool_bytes)
    : channel_id_(std::move(channel_id)),
      playout_session_id_(std::move(playout_session_id)),
      max_spool_bytes_(max_spool_bytes),
      last_flush_time_(std::chrono::steady_clock::now()) {
  spool_dir_ = spool_root + "/" + channel_id_;
  spool_path_ = spool_dir_ + "/" + playout_session_id_ + ".spool.jsonl";
  ack_path_ = spool_dir_ + "/" + playout_session_id_ + ".ack";

  // Create spool_root then spool_dir_ (mkdir -p style)
  if (mkdir(spool_root.c_str(), 0755) != 0 && errno != EEXIST) {
    throw std::runtime_error("EvidenceSpool: cannot create directory " + spool_root);
  }
  if (mkdir(spool_dir_.c_str(), 0755) != 0 && errno != EEXIST) {
    throw std::runtime_error("EvidenceSpool: cannot create directory " + spool_dir_);
  }

  // Seed estimated_spool_bytes_ from existing file size (for restart scenarios).
  struct stat st;
  if (stat(spool_path_.c_str(), &st) == 0) {
    estimated_spool_bytes_ = static_cast<size_t>(st.st_size);
  }

  writer_thread_ = std::thread(&EvidenceSpool::WriterLoop, this);
}

EvidenceSpool::~EvidenceSpool() {
  {
    std::lock_guard<std::mutex> lock(queue_mutex_);
    shutdown_ = true;
    queue_cv_.notify_all();
  }
  if (writer_thread_.joinable())
    writer_thread_.join();
}

std::string EvidenceSpool::SpoolPath() const { return spool_path_; }
std::string EvidenceSpool::AckPath() const { return ack_path_; }

AppendStatus EvidenceSpool::Append(const EvidenceFromAir& msg) {
  std::lock_guard<std::mutex> lock(queue_mutex_);
  if (last_appended_sequence_ != 0 && msg.sequence != last_appended_sequence_ + 1)
    throw std::runtime_error("EvidenceSpool: sequence gap detected (expected " +
                             std::to_string(last_appended_sequence_ + 1) + ", got " +
                             std::to_string(msg.sequence) + ")");

  // SP-RET-003: Check disk cap before accepting new record.
  // Cap applies to pending/unacked bytes to allow recovery when ACKs advance.
  {
    size_t record_bytes = msg.ToJsonLine().size() + 1;
    if (max_spool_bytes_ > 0) {
      size_t pending = estimated_spool_bytes_ - acked_byte_offset_;
      if (pending + record_bytes > max_spool_bytes_) {
        return AppendStatus::kSpoolFull;
      }
    }
    estimated_spool_bytes_ += record_bytes;
    record_byte_sizes_.push_back(record_bytes);
  }

  last_appended_sequence_ = msg.sequence;
  write_queue_.push_back(msg);
  records_since_flush_++;
  if (write_queue_.size() >= kFlushRecordsMax)
    queue_cv_.notify_one();
  return AppendStatus::kOk;
}

size_t EvidenceSpool::CurrentSpoolBytes() const {
  // Note: not locked — best-effort read for diagnostics.
  return estimated_spool_bytes_;
}

void EvidenceSpool::WriterLoop() {
  while (true) {
    std::unique_lock<std::mutex> lock(queue_mutex_);
    queue_cv_.wait_for(lock, std::chrono::milliseconds(kFlushIntervalMs), [this] {
      return shutdown_ || !write_queue_.empty();
    });
    if (shutdown_ && write_queue_.empty()) break;
    std::vector<EvidenceFromAir> batch;
    batch.swap(write_queue_);
    auto now = std::chrono::steady_clock::now();
    bool flush_due = shutdown_ || batch.empty() == false ||
                     records_since_flush_ >= kFlushRecordsMax ||
                     (now - last_flush_time_) >= std::chrono::milliseconds(kFlushIntervalMs);
    if (!batch.empty())
      records_since_flush_ = 0;
    last_flush_time_ = now;
    lock.unlock();

    if (batch.empty()) continue;

    std::ofstream of(spool_path_, std::ios::app);
    if (!of)
      throw std::runtime_error("EvidenceSpool: cannot open spool file " + spool_path_);
    for (const auto& msg : batch)
      of << msg.ToJsonLine() << '\n';
    of.flush();
    if (!of)
      throw std::runtime_error("EvidenceSpool: write failed " + spool_path_);
  }
}

void EvidenceSpool::FlushPending() {
  std::lock_guard<std::mutex> lock(queue_mutex_);
  queue_cv_.notify_all();
}

std::vector<EvidenceFromAir> EvidenceSpool::ReplayFrom(uint64_t acked_sequence) const {
  std::ifstream in(spool_path_);
  if (!in) return {};

  std::vector<EvidenceFromAir> result;
  std::string line;
  while (std::getline(in, line)) {
    if (line.empty()) continue;
    EvidenceFromAir msg;
    if (!EvidenceFromAir::FromJsonLine(line, msg))
      continue;  // SP-CRASH-002: ignore corrupt/incomplete final line
    if (msg.sequence > acked_sequence)
      result.push_back(std::move(msg));
  }
  return result;
}

size_t EvidenceSpool::PendingBytes() const {
  return estimated_spool_bytes_ - acked_byte_offset_;
}

void EvidenceSpool::UpdateAck(uint64_t seq) {
  uint64_t current = GetLastAck();
  if (seq <= current) return;

  // Advance byte tracking cursor — sequences are strictly monotonic.
  // record_byte_sizes_ is 0-indexed (entry 0 = sequence 1).
  while (ack_cursor_ < seq && ack_cursor_ < record_byte_sizes_.size()) {
    acked_byte_offset_ += record_byte_sizes_[ack_cursor_];
    ack_cursor_++;
  }

  std::string iso8601;
  {
    auto now = std::chrono::system_clock::now();
    auto ms = std::chrono::duration_cast<std::chrono::milliseconds>(now.time_since_epoch()).count();
    time_t s = static_cast<time_t>(ms / 1000);
    int frac_ms = static_cast<int>(ms % 1000);
    struct tm tm;
    if (gmtime_r(&s, &tm) == nullptr) return;
    char buf[64];
    int n = snprintf(buf, sizeof(buf), "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ",
                    tm.tm_year + 1900, tm.tm_mon + 1, tm.tm_mday,
                    tm.tm_hour, tm.tm_min, tm.tm_sec, frac_ms);
    if (n <= 0 || n >= static_cast<int>(sizeof(buf))) return;
    iso8601.assign(buf, static_cast<size_t>(n));
  }

  std::string content = "acked_sequence=" + std::to_string(seq) + "\nupdated_utc=" + iso8601 + "\n";
  std::string tmp_path = ack_path_ + ".tmp." + std::to_string(static_cast<unsigned long>(getpid()));
  {
    std::ofstream of(tmp_path, std::ios::out | std::ios::trunc);
    if (!of) {
      // Fallback: write directly when tmp (e.g. same dir) cannot be created
      std::ofstream direct(ack_path_, std::ios::out | std::ios::trunc);
      if (direct) {
        direct << content;
        direct.flush();
      }
      return;
    }
    of << content;
    of.flush();
    if (!of) return;
    of.close();
    if (!of) return;
  }
  if (rename(tmp_path.c_str(), ack_path_.c_str()) != 0) {
    (void)unlink(tmp_path.c_str());
    std::ofstream of(ack_path_, std::ios::out | std::ios::trunc);
    if (of) {
      of << content;
      of.flush();
    }
  }
}

uint64_t EvidenceSpool::GetLastAck() const {
  std::ifstream in(ack_path_);
  if (!in) return 0;
  std::string line;
  if (!std::getline(in, line) || line.find("acked_sequence=") != 0) return 0;
  try {
    return static_cast<uint64_t>(std::stoull(line.substr(15)));
  } catch (...) {
    return 0;
  }
}

}  // namespace retrovue::evidence
