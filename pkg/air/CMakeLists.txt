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

# ---- Proto: execution_evidence_v1.proto (AIR → Core evidence stream) ----
set(EVIDENCE_PROTO "${CMAKE_CURRENT_SOURCE_DIR}/../../protos/execution_evidence_v1.proto")
get_filename_component(EVIDENCE_PROTO "${EVIDENCE_PROTO}" ABSOLUTE)

set(EVIDENCE_PB_CC "${PROTO_GEN_DIR}/execution_evidence_v1.pb.cc")
set(EVIDENCE_PB_H  "${PROTO_GEN_DIR}/execution_evidence_v1.pb.h")
set(EVIDENCE_GRPC_CC "${PROTO_GEN_DIR}/execution_evidence_v1.grpc.pb.cc")
set(EVIDENCE_GRPC_H  "${PROTO_GEN_DIR}/execution_evidence_v1.grpc.pb.h")

add_custom_command(
  OUTPUT "${EVIDENCE_PB_CC}" "${EVIDENCE_PB_H}" "${EVIDENCE_GRPC_CC}" "${EVIDENCE_GRPC_H}"
  COMMAND "${CMAKE_COMMAND}" -E make_directory "${PROTO_GEN_DIR}"
  COMMAND "$<TARGET_FILE:protobuf::protoc>"
    --proto_path="${PROTO_IMPORT_DIR}"
    --cpp_out="${PROTO_GEN_DIR}"
    --grpc_out="${PROTO_GEN_DIR}"
    --plugin=protoc-gen-grpc="${GRPC_PLUGIN_EXE}"
    "${EVIDENCE_PROTO}"
  DEPENDS "${EVIDENCE_PROTO}"
  COMMENT "Generating C++ from ${EVIDENCE_PROTO}"
)

add_library(evidence_proto
  "${EVIDENCE_PB_CC}"
  "${EVIDENCE_GRPC_CC}"
)

target_link_libraries(evidence_proto
  PUBLIC
    protobuf::libprotobuf
    gRPC::grpc++
)

target_include_directories(evidence_proto
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
  src/blockplan/FFmpegDecoderAdapter.cpp
  src/blockplan/TickProducer.cpp
  src/blockplan/ProducerPreloader.cpp
  src/blockplan/SeamPreparer.cpp
  src/blockplan/PipelineManager.cpp
  src/time/SystemTimeSource.cpp
  # AudioLookaheadBuffer: broadcast-grade audio buffering (INV-AUDIO-LOOKAHEAD-001)
  src/blockplan/AudioLookaheadBuffer.cpp
  # VideoLookaheadBuffer: non-blocking video buffering (INV-VIDEO-LOOKAHEAD-001)
  src/blockplan/VideoLookaheadBuffer.cpp
  # Evidence spool + emitter (AirExecutionEvidenceSpoolContract_v0.1)
  src/evidence/EvidenceSpool.cpp
  src/evidence/EvidenceEmitter.cpp
  # Evidence gRPC client (ExecutionEvidenceGrpcInterfaceContract_v0.1)
  src/evidence/GrpcEvidenceClient.cpp
  # Thread-safe logger (prevents multi-thread log interleave)
  src/util/Logger.cpp
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
    evidence_proto
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
  tests/contracts/file_producer/FpsResampleTests.cpp
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
  # NOTE: BlockPlanContractTests.cpp excluded — depends on removed BlockPlanQueue.hpp
  # (removed in 497a9d6). Object was stale-cached; exposed by clean rebuild.
  tests/blockplan/test_segment_transitions.cpp
  tests/contracts/BlockPlan/PTSContinuityContractTests.cpp
  tests/contracts/BlockPlan/ExecutionEngineGuardrailTests.cpp
  tests/contracts/BlockPlan/ContinuousOutputContractTests.cpp
  tests/contracts/BlockPlan/SeamProofContractTests.cpp
  tests/contracts/BlockPlan/TakeAtCommitContractTests.cpp
  tests/contracts/BlockPlan/PadProducerContractTests.cpp
  tests/contracts/BlockPlan/PlaybackTraceContractTests.cpp
  tests/contracts/BlockPlan/AudioLookaheadBufferTests.cpp
  tests/contracts/BlockPlan/SegmentAdvanceOnEOFTests.cpp
  tests/contracts/BlockPlan/SegmentContinuityContractTests.cpp
  tests/contracts/BlockPlan/ProgramBlockAuthorityContractTests.cpp
  tests/contracts/BlockPlan/SeamContinuityEngineContractTests.cpp
  tests/contracts/BlockPlan/SegmentSeamOverlapContractTests.cpp
  tests/contracts/BlockPlan/SegmentSeamRaceConditionFixTests.cpp
  tests/contracts/BlockPlan/DegradedTakeModeContractTests.cpp
  tests/blockplan/test_segment_aware_playback_proof.cpp
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
    ${CMAKE_CURRENT_SOURCE_DIR}/tests/support
)

# Optional: build with -DRETROVUE_FAST_TEST=1 for short-duration deterministic tests.
if(RETROVUE_FAST_TEST)
  target_compile_definitions(blockplan_contract_tests PRIVATE RETROVUE_FAST_TEST)
endif()

add_test(
  NAME BlockPlanContracts
  COMMAND blockplan_contract_tests
)

# ---- BlockPlan Slow Contract Tests ----
# Runs the DISABLED_SLOW_* tests from the same binary.
# These are long-running real-media or multi-swap tests moved out of the fast suite.
add_test(
  NAME BlockPlanSlowContracts
  COMMAND blockplan_contract_tests --gtest_also_run_disabled_tests --gtest_filter=*SLOW_*
)

# ---- AudioLookaheadBuffer Contract Tests (INV-AUDIO-LOOKAHEAD-001) ----
add_executable(audio_lookahead_tests
  tests/contracts/BlockPlan/AudioLookaheadBufferTests.cpp
)

target_link_libraries(audio_lookahead_tests
  PRIVATE
    retrovue_air_core
    GTest::gtest
    GTest::gtest_main
)

target_include_directories(audio_lookahead_tests
  PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}/include
    ${CMAKE_CURRENT_SOURCE_DIR}/tests/contracts/BlockPlan
)

add_test(
  NAME AudioLookaheadContracts
  COMMAND audio_lookahead_tests
)

# ---- VideoLookaheadBuffer Contract Tests (INV-VIDEO-LOOKAHEAD-001) ----
add_executable(video_lookahead_tests
  tests/contracts/BlockPlan/VideoLookaheadBufferTests.cpp
)

target_link_libraries(video_lookahead_tests
  PRIVATE
    retrovue_air_core
    GTest::gtest
    GTest::gtest_main
)

target_include_directories(video_lookahead_tests
  PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}/include
    ${CMAKE_CURRENT_SOURCE_DIR}/tests/contracts/BlockPlan
)

add_test(
  NAME VideoLookaheadContracts
  COMMAND video_lookahead_tests
)

# ---- Lookahead Buffer Contract Tests (INV-VIDEO-LOOKAHEAD-001 + INV-AUDIO-LOOKAHEAD-001) ----
# Enforces: tick-thread-never-decodes, underflow-is-hard-fault, fence-tick precision.
add_executable(lookahead_contract_tests
  tests/contracts/BlockPlan/LookaheadBufferContractTests.cpp
)

target_link_libraries(lookahead_contract_tests
  PRIVATE
    retrovue_air_core
    GTest::gtest
    GTest::gtest_main
)

target_include_directories(lookahead_contract_tests
  PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}/include
    ${CMAKE_CURRENT_SOURCE_DIR}/tests/contracts/BlockPlan
)

add_test(
  NAME LookaheadBufferContracts
  COMMAND lookahead_contract_tests
)

# ---- BufferConfig Contract Tests (configurable depths, low-water, decode latency) ----
add_executable(buffer_config_tests
  tests/contracts/BlockPlan/BufferConfigTests.cpp
)

target_link_libraries(buffer_config_tests
  PRIVATE
    retrovue_air_core
    GTest::gtest
    GTest::gtest_main
)

target_include_directories(buffer_config_tests
  PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}/include
    ${CMAKE_CURRENT_SOURCE_DIR}/tests/contracts/BlockPlan
)

add_test(
  NAME BufferConfigContracts
  COMMAND buffer_config_tests
)

# ---- Evidence Spool Contract Tests (AirExecutionEvidenceSpoolContract_v0.1) ----
add_executable(evidence_spool_tests
  tests/test_evidence_spool.cpp
)

target_link_libraries(evidence_spool_tests
  PRIVATE
    retrovue_air_core
    GTest::gtest
    GTest::gtest_main
)

target_include_directories(evidence_spool_tests
  PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}/src
    ${CMAKE_CURRENT_SOURCE_DIR}/include
)

add_test(
  NAME EvidenceSpoolContracts
  COMMAND evidence_spool_tests
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

# ---- Architectural Guardrail: No As-Run Artifacts from AIR ----
# Core is the sole as-run authority. AIR emits evidence via EvidenceEmitter only.
add_executable(no_asrun_guardrail_test
  tests/contracts/BlockPlan/NoAsRunArtifactGuardrailTest.cpp
)
target_link_libraries(no_asrun_guardrail_test PRIVATE GTest::gtest GTest::gtest_main)
target_include_directories(no_asrun_guardrail_test PRIVATE
  ${CMAKE_CURRENT_SOURCE_DIR}/include
)
add_test(NAME NoAsRunArtifactGuardrail COMMAND no_asrun_guardrail_test)

# ---- P3.2: Seam Verify Standalone Harness ----
# Standalone binary for real-media boundary verification using PipelineManager.
add_executable(retrovue_air_seam_verify
  src/standalone/SeamVerifyMain.cpp
)
target_link_libraries(retrovue_air_seam_verify PRIVATE retrovue_air_core)
target_include_directories(retrovue_air_seam_verify PRIVATE
  ${CMAKE_CURRENT_SOURCE_DIR}/include
)
