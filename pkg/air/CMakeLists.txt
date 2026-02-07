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
# Phase 8.1.5: libav* REQUIRED for in-process decode (no ffmpeg executable). No fallback.
# All C++ and Air build assets live under pkg/air (multiplatform repo invariant).
set(AIR_ROOT "${CMAKE_CURRENT_SOURCE_DIR}")
# FFmpeg: static build from pkg/air/scripts/build_ffmpeg_static.sh → pkg/air/third_party/ffmpeg/install
set(FFMPEG_INSTALL "${AIR_ROOT}/third_party/ffmpeg/install")
set(FFMPEG_INCLUDE_DIR "${FFMPEG_INSTALL}/include")
set(FFMPEG_LIB_DIR "${FFMPEG_INSTALL}/lib")
# x264: private third-party dependency; only pkg/air/third_party/x264/install (never src tree).
set(X264_ROOT "${AIR_ROOT}/third_party/x264/install")
set(X264_LIB_DIR "${X264_ROOT}/lib")

# Locate x264 only under third_party/x264/install/lib. Prefer static (libx264.a).
find_library(X264_LIB
  NAMES libx264.a libx264.so libx264.so.165
  PATHS "${X264_LIB_DIR}"
  NO_DEFAULT_PATH
)
if(NOT X264_LIB)
  message(FATAL_ERROR "x264 not found in ${X264_LIB_DIR}. Build and install x264 into pkg/air/third_party/x264/install (lib/libx264.a or lib/libx264.so). If FFmpeg was built with shared libx264, install must contain lib/libx264.so (or libx264.so.165).")
endif()
if(X264_LIB MATCHES "\\.a$")
  add_library(x264 STATIC IMPORTED)
else()
  add_library(x264 SHARED IMPORTED)
endif()
set_target_properties(x264 PROPERTIES
  IMPORTED_LOCATION "${X264_LIB}"
  INTERFACE_INCLUDE_DIRECTORIES "${X264_ROOT}/include"
)

# Static FFmpeg libs from pkg/air/third_party/ffmpeg/install (build via pkg/air/scripts/build_ffmpeg_static.sh).
find_library(FFMPEG_avformat NAMES libavformat.a PATHS "${FFMPEG_LIB_DIR}" NO_DEFAULT_PATH)
find_library(FFMPEG_avcodec NAMES libavcodec.a PATHS "${FFMPEG_LIB_DIR}" NO_DEFAULT_PATH)
find_library(FFMPEG_swscale NAMES libswscale.a PATHS "${FFMPEG_LIB_DIR}" NO_DEFAULT_PATH)
find_library(FFMPEG_swresample NAMES libswresample.a PATHS "${FFMPEG_LIB_DIR}" NO_DEFAULT_PATH)
find_library(FFMPEG_avutil NAMES libavutil.a PATHS "${FFMPEG_LIB_DIR}" NO_DEFAULT_PATH)
foreach(LIB avformat avcodec swscale swresample avutil)
  if(NOT FFMPEG_${LIB})
    message(FATAL_ERROR "FFmpeg static lib ${LIB} not found in ${FFMPEG_LIB_DIR}. Run pkg/air/scripts/build_ffmpeg_static.sh first.")
  endif()
endforeach()
set(LIBAV_LIBRARIES_STATIC
  ${FFMPEG_avformat}
  ${FFMPEG_avcodec}
  ${FFMPEG_swscale}
  ${FFMPEG_swresample}
  ${FFMPEG_avutil}
)

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

# ---- BlockPlan shared infrastructure ----
# Contract Reference: docs/architecture/proposals/BlockLevelPlayoutAutonomy.md
set(BLOCKPLAN_SOURCES
  src/blockplan/BlockPlanTypes.cpp
  src/blockplan/BlockPlanValidator.cpp
)

add_library(retrovue_blockplan ${BLOCKPLAN_SOURCES})
target_include_directories(retrovue_blockplan
  PUBLIC
    ${CMAKE_CURRENT_SOURCE_DIR}/include
    ${CMAKE_CURRENT_SOURCE_DIR}/tests/contracts/BlockPlan
)
target_compile_features(retrovue_blockplan PUBLIC cxx_std_20)

# ---- Air engine (control-surface-only capable; paths match repo layout) ----
# Core service + runtime
set(AIR_CORE_SOURCES
  src/playout_service.cpp
  src/runtime/PlayoutInterface.cpp
  src/runtime/PlayoutEngine.cpp
  src/runtime/ProgramFormat.cpp
  src/runtime/PlayoutControl.cpp
  src/runtime/TimingLoop.cpp
  src/runtime/ProducerBus.cpp
  src/buffer/FrameRingBuffer.cpp
  src/decode/FrameProducer.cpp
  src/decode/FFmpegDecoder.cpp
  src/renderer/ProgramOutput.cpp
  src/telemetry/MetricsExporter.cpp
  src/telemetry/MetricsHTTPServer.cpp
  src/timing/SystemMasterClock.cpp
  src/timing/TimelineController.cpp
  src/producers/file/FileProducer.cpp
  src/producers/programmatic/ProgrammaticProducer.cpp
  src/producers/black/BlackFrameProducer.cpp
  src/playout_sinks/mpegts/EncoderPipeline.cpp
  src/playout_sinks/mpegts/PTSController.cpp
  # Phase 9.0: OutputBus/OutputSink architecture
  src/output/OutputBus.cpp
  src/output/MpegTSOutputSink.cpp
  src/output/SocketSink.cpp
  # BlockPlan asset probing (used by TickProducer)
  src/blockplan/RealAssetSource.cpp
  # PipelineManager playout engine (P3.0 + P3.1a + P3.1b: pad + A/B producer swap)
  src/blockplan/OutputClock.cpp
  src/blockplan/TickProducer.cpp
  src/blockplan/ProducerPreloader.cpp
  src/blockplan/PipelineManager.cpp
)

add_library(retrovue_air_core ${AIR_CORE_SOURCES})

target_compile_definitions(retrovue_air_core PUBLIC RETROVUE_FFMPEG_AVAILABLE)
target_include_directories(retrovue_air_core PUBLIC "${FFMPEG_INCLUDE_DIR}")
target_include_directories(retrovue_air_core
  PUBLIC
    ${CMAKE_CURRENT_SOURCE_DIR}/include
    ${CMAKE_CURRENT_SOURCE_DIR}/src
    ${PROTO_GEN_DIR}
)
target_link_directories(retrovue_air_core PUBLIC "${FFMPEG_LIB_DIR}" "${X264_LIB_DIR}")
# FFmpeg static libs first, then x264 so avcodec's x264 refs resolve. Then deps FFmpeg needs.
target_link_libraries(retrovue_air_core
  PUBLIC
    playout_proto
    retrovue_blockplan
    gRPC::grpc++
    ${LIBAV_LIBRARIES_STATIC}
    x264
    Threads::Threads
    m
    z
    lzma
    bz2
)
# RPATH for any shared deps (binaries under pkg/air/build); harmless when everything is static.
set(X264_RPATH "\$ORIGIN/../third_party/x264/install/lib")
set(FFMPEG_RPATH "\$ORIGIN/../third_party/ffmpeg/install/lib")
target_link_options(retrovue_air_core PRIVATE
  "LINKER:-rpath,${X264_RPATH}"
  "LINKER:-rpath,${FFMPEG_RPATH}"
)

# ---- gRPC server executable (Phase 8.0: AttachStream/DetachStream over UDS) ----
add_executable(retrovue_air src/main.cpp)
target_link_libraries(retrovue_air
  PRIVATE
    retrovue_air_core
    gRPC::grpc++_reflection
)
target_link_options(retrovue_air PRIVATE
  "LINKER:-rpath,${X264_RPATH}"
  "LINKER:-rpath,${FFMPEG_RPATH}"
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
  tests/contracts/OutputSwitching/OutputSwitchingContractTests.cpp
  tests/contracts/Phase815FileProducerTests.cpp
  tests/contracts/Phase84PersistentMpegTsMuxTests.cpp
  tests/contracts/file_producer/FileProducerContractTests.cpp
  tests/contracts/TimelineController/TimelineControllerContractTests.cpp
  tests/contracts/TimelineController/Phase8IntegrationTests.cpp
  tests/contracts/Phase9OutputBootstrapTests.cpp
  tests/contracts/Phase9SteadyStateSilenceTests.cpp
  tests/contracts/Phase9SymmetricBackpressureTests.cpp
  tests/contracts/Phase9NoPadWhileDepthHighTests.cpp
  tests/contracts/Phase9BufferEquilibriumTests.cpp
  tests/contracts/Phase10PipelineFlowControlTests.cpp
  tests/contracts/Phase10FrameIndexedExecutionTests.cpp
  tests/contracts/Phase11AudioContinuityTests.cpp
  tests/contracts/BoundaryDeclarationTests.cpp
  tests/contracts/PrefeedProtocolTests.cpp
  tests/contracts/DeadlineSwitchTests.cpp
  # INV-PACING-001: Primitive invariant contract tests (locks pacing as solved)
  tests/contracts/PrimitiveInvariants/PacingInvariantContractTests.cpp
  # INV-P9-SINK-LIVENESS: Sink liveness policy contract tests
  tests/contracts/PrimitiveInvariants/SinkLivenessContractTests.cpp
  # INV-P8-PRODUCER-CONTINUITY: Producer handoff continuity contract tests
  tests/contracts/ProducerContinuity/ProducerContinuityContractTests.cpp
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
target_link_options(contracts_playoutengine_tests PRIVATE
  "LINKER:-rpath,${X264_RPATH}"
  "LINKER:-rpath,${FFMPEG_RPATH}"
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

# DISABLED: Known deadlock / infinite loop in test infrastructure
# Uses legacy PlayoutEngine/PlayoutControl — not the current PipelineManager path
# add_test(
#   NAME PlayoutEngineContracts
#   COMMAND contracts_playoutengine_tests
# )

# ---- Deterministic Harness Contract Tests ----
# Tests control-plane and continuity invariants without real media files.
# NOTE: These tests are designed to FAIL until BlackFrameProducer is implemented.
add_executable(deterministic_harness_tests
  tests/harness/deterministic/FakeProducers.cpp
  tests/harness/deterministic/RecordingSink.cpp
  tests/harness/deterministic/DeterministicTestHarness.cpp
  tests/contracts/DeterministicHarness/DeterministicHarnessContractTests.cpp
  tests/ContractRegistry.cpp
  tests/contracts/ContractRegistryEnvironment.cpp
  src/timing/TestMasterClock.cpp
)

target_link_libraries(deterministic_harness_tests
  PRIVATE
    retrovue_air_core
    GTest::gtest
    GTest::gtest_main
)

target_link_options(deterministic_harness_tests PRIVATE
  "LINKER:-rpath,${X264_RPATH}"
  "LINKER:-rpath,${FFMPEG_RPATH}"
)

target_include_directories(deterministic_harness_tests
  PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}/tests
    ${CMAKE_CURRENT_SOURCE_DIR}/tests/contracts
    ${CMAKE_CURRENT_SOURCE_DIR}/tests/harness
    ${CMAKE_CURRENT_SOURCE_DIR}/src
    ${CMAKE_CURRENT_SOURCE_DIR}/include
)

add_test(
  NAME DeterministicHarnessContracts
  COMMAND deterministic_harness_tests
)

# ---- BlockPlan Contract Tests (Section 7) ----
# Tests for docs/architecture/proposals/BlockLevelPlayoutAutonomy.md
add_executable(blockplan_contract_tests
  tests/contracts/BlockPlan/BlockPlanContractTests.cpp
  tests/contracts/BlockPlan/PTSContinuityContractTests.cpp
  tests/contracts/BlockPlan/ExecutionEngineGuardrailTests.cpp
  tests/contracts/BlockPlan/ContinuousOutputContractTests.cpp
  tests/contracts/BlockPlan/SeamProofContractTests.cpp
  tests/contracts/BlockPlan/PlaybackTraceContractTests.cpp
)

target_link_libraries(blockplan_contract_tests
  PRIVATE
    retrovue_air_core
    GTest::gtest
    GTest::gtest_main
)

target_include_directories(blockplan_contract_tests
  PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}/include
    ${CMAKE_CURRENT_SOURCE_DIR}/tests/contracts/BlockPlan
)

add_test(
  NAME BlockPlanContracts
  COMMAND blockplan_contract_tests
)

# ---- Media Time Contract Tests (INV-AIR-MEDIA-TIME-001..005) ----
# Deterministic tests verifying PTS-anchored media time tracking.
# No video files needed — uses simulated decoder PTS values.
add_executable(mediatime_contract_tests
  tests/contracts/BlockPlan/MediaTimeContractTests.cpp
)

target_link_libraries(mediatime_contract_tests
  PRIVATE
    retrovue_air_core
    GTest::gtest
    GTest::gtest_main
)

target_link_options(mediatime_contract_tests PRIVATE
  "LINKER:-rpath,${X264_RPATH}"
  "LINKER:-rpath,${FFMPEG_RPATH}"
)

target_include_directories(mediatime_contract_tests
  PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}/include
    ${CMAKE_CURRENT_SOURCE_DIR}/tests/contracts/BlockPlan
)

add_test(
  NAME MediaTimeContracts
  COMMAND mediatime_contract_tests
)

# ---- P3.2: Seam Verify Standalone Harness ----
# Standalone binary for real-media boundary verification using PipelineManager.
add_executable(retrovue_air_seam_verify
  src/standalone/SeamVerifyMain.cpp
)
target_link_libraries(retrovue_air_seam_verify PRIVATE retrovue_air_core)
target_include_directories(retrovue_air_seam_verify PRIVATE
  ${CMAKE_CURRENT_SOURCE_DIR}/include
)
