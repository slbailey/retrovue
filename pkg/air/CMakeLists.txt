# Phase 6A.0 — minimal but real. Explicit so Cursor (and CMake) understand it.
#
# Build (with vcpkg):
#   cmake -S pkg/air -B pkg/air/build \
#     -DCMAKE_TOOLCHAIN_FILE=$VCPKG_ROOT/scripts/buildsystems/vcpkg.cmake \
#     -DCMAKE_BUILD_TYPE=RelWithDebInfo
#   cmake --build pkg/air/build --target contracts_playoutengine_tests
#   ctest --test-dir pkg/air/build --output-on-failure
#
cmake_minimum_required(VERSION 3.21)
project(retrovue_air LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# ---- Dependencies (via vcpkg or system) ----
find_package(Protobuf CONFIG REQUIRED)
find_package(gRPC CONFIG REQUIRED)
find_package(GTest CONFIG REQUIRED)

# ---- Proto (canonical path: repo root protos/playout.proto) ----
set(PLAYOUT_PROTO "${CMAKE_CURRENT_SOURCE_DIR}/../../protos/playout.proto")
get_filename_component(PLAYOUT_PROTO "${PLAYOUT_PROTO}" ABSOLUTE)
get_filename_component(PROTO_IMPORT_DIR "${PLAYOUT_PROTO}" DIRECTORY)
# Use the directory containing the .proto so generated files land in PROTO_GEN_DIR as playout.pb.cc (no protos/ subdir)
set(PROTO_GEN_DIR "${CMAKE_CURRENT_BINARY_DIR}")

# Generated filenames (from playout.proto)
set(PROTO_PB_CC "${PROTO_GEN_DIR}/playout.pb.cc")
set(PROTO_PB_H  "${PROTO_GEN_DIR}/playout.pb.h")
set(PROTO_GRPC_CC "${PROTO_GEN_DIR}/playout.grpc.pb.cc")
set(PROTO_GRPC_H  "${PROTO_GEN_DIR}/playout.grpc.pb.h")

# Generator expressions in add_custom_command (CMake 3.20+)
cmake_policy(SET CMP0112 NEW)

# gRPC plugin: vcpkg exposes gRPC::grpc_cpp_plugin when codegen is installed
if(TARGET gRPC::grpc_cpp_plugin)
  set(GRPC_PLUGIN_EXE "$<TARGET_FILE:gRPC::grpc_cpp_plugin>")
else()
  find_program(GRPC_CPP_PLUGIN_EXE grpc_cpp_plugin REQUIRED)
  set(GRPC_PLUGIN_EXE "${GRPC_CPP_PLUGIN_EXE}")
endif()

add_custom_command(
  OUTPUT "${PROTO_PB_CC}" "${PROTO_PB_H}" "${PROTO_GRPC_CC}" "${PROTO_GRPC_H}"
  COMMAND "${CMAKE_COMMAND}" -E make_directory "${PROTO_GEN_DIR}"
  COMMAND "$<TARGET_FILE:protobuf::protoc>"
    --proto_path="${PROTO_IMPORT_DIR}"
    --cpp_out="${PROTO_GEN_DIR}"
    --grpc_out="${PROTO_GEN_DIR}"
    --plugin=protoc-gen-grpc="${GRPC_PLUGIN_EXE}"
    "${PLAYOUT_PROTO}"
  DEPENDS "${PLAYOUT_PROTO}"
  COMMENT "Generating C++ from ${PLAYOUT_PROTO}"
)

add_library(playout_proto
  "${PROTO_PB_CC}"
  "${PROTO_GRPC_CC}"
)

target_link_libraries(playout_proto
  PUBLIC
    protobuf::libprotobuf
    gRPC::grpc++
)

target_include_directories(playout_proto
  PUBLIC
    "${PROTO_GEN_DIR}"
)

# ---- Air engine (control-surface-only capable; paths match repo layout) ----
# Core service + runtime
set(AIR_CORE_SOURCES
  src/playout_service.cpp
  src/runtime/PlayoutController.cpp
  src/runtime/PlayoutEngine.cpp
  src/runtime/PlayoutControlStateMachine.cpp
  src/runtime/OrchestrationLoop.cpp
  src/runtime/ProducerSlot.cpp
  src/buffer/FrameRingBuffer.cpp
  src/decode/FrameProducer.cpp
  src/decode/FFmpegDecoder.cpp
  src/renderer/FrameRenderer.cpp
  src/telemetry/MetricsExporter.cpp
  src/telemetry/MetricsHTTPServer.cpp
  src/timing/SystemMasterClock.cpp
  src/producers/video_file/VideoFileProducer.cpp
  src/producers/programmatic/ProgrammaticProducer.cpp
)

add_library(retrovue_air_core ${AIR_CORE_SOURCES})

target_link_libraries(retrovue_air_core
  PUBLIC
    playout_proto
    gRPC::grpc++
)

target_include_directories(retrovue_air_core
  PUBLIC
    ${CMAKE_CURRENT_SOURCE_DIR}/include
    ${CMAKE_CURRENT_SOURCE_DIR}/src
    ${PROTO_GEN_DIR}
)

# ---- gRPC server executable (Phase 8.0: AttachStream/DetachStream over UDS) ----
add_executable(retrovue_air src/main.cpp)
target_link_libraries(retrovue_air
  PRIVATE
    retrovue_air_core
    gRPC::grpc++_reflection
)
target_include_directories(retrovue_air
  PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}/src
    ${CMAKE_CURRENT_SOURCE_DIR}/include
    ${PROTO_GEN_DIR}
)

# ---- Contract tests (Phase 6A.0: PlayoutEngine + control surface) ----
add_executable(contracts_playoutengine_tests
  tests/contracts/PlayoutEngine/PlayoutEngineContractTests.cpp
  tests/ContractRegistry.cpp
  tests/contracts/ContractRegistryEnvironment.cpp
  src/timing/TestMasterClock.cpp
)

target_link_libraries(contracts_playoutengine_tests
  PRIVATE
    retrovue_air_core
    GTest::gtest
    GTest::gtest_main
)

target_include_directories(contracts_playoutengine_tests
  PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}/tests
    ${CMAKE_CURRENT_SOURCE_DIR}/tests/contracts
    ${CMAKE_CURRENT_SOURCE_DIR}/tests/fixtures
    ${CMAKE_CURRENT_SOURCE_DIR}/src
    ${CMAKE_CURRENT_SOURCE_DIR}/include
)

enable_testing()
add_test(
  NAME PlayoutEngineContracts
  COMMAND contracts_playoutengine_tests
)
