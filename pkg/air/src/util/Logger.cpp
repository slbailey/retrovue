// Repository: Retrovue-playout
// Component: Thread-Safe Logger
// Purpose: Mutex-protected log emission — prevents multi-thread interleave.
// Copyright (c) 2025 RetroVue

#include "retrovue/util/Logger.hpp"

#include <cstdlib>
#include <iostream>

namespace retrovue::util {

std::mutex Logger::mutex_;
std::function<void(const std::string&)> Logger::error_sink_;
std::function<void(const std::string&)> Logger::info_sink_;

void Logger::SetErrorSink(std::function<void(const std::string&)> sink) {
  std::lock_guard<std::mutex> lock(mutex_);
  error_sink_ = std::move(sink);
}

void Logger::SetInfoSink(std::function<void(const std::string&)> sink) {
  std::lock_guard<std::mutex> lock(mutex_);
  info_sink_ = std::move(sink);
}

void Logger::Info(const std::string& line) {
  std::lock_guard<std::mutex> lock(mutex_);
  if (info_sink_) {
    info_sink_(line);
  }
  std::cout << line << '\n';
  std::cout.flush();
}

void Logger::Debug(const std::string& line) {
  if (std::getenv("RETROVUE_DEBUG") == nullptr) return;
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
