// Repository: Retrovue-playout
// Component: Thread-Safe Logger
// Purpose: Mutex-protected log emission — prevents multi-thread interleave.
// Copyright (c) 2025 RetroVue

#include "retrovue/util/Logger.hpp"

#include <iostream>

namespace retrovue::util {

std::mutex Logger::mutex_;
std::function<void(const std::string&)> Logger::error_sink_;

void Logger::SetErrorSink(std::function<void(const std::string&)> sink) {
  std::lock_guard<std::mutex> lock(mutex_);
  error_sink_ = std::move(sink);
}

void Logger::Info(const std::string& line) {
  std::lock_guard<std::mutex> lock(mutex_);
  std::cout << line << '\n';
  std::cout.flush();
}

void Logger::Warn(const std::string& line) {
  std::lock_guard<std::mutex> lock(mutex_);
  std::cerr << line << '\n';
  std::cerr.flush();
}

void Logger::Error(const std::string& line) {
  std::lock_guard<std::mutex> lock(mutex_);
  if (error_sink_) {
    error_sink_(line);
  }
  std::cerr << line << '\n';
  std::cerr.flush();
}

}  // namespace retrovue::util
