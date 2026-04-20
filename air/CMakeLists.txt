# AIR vNext — first slice.
#
# Build (from repo root, with vcpkg):
#   cmake -S air -B air/build \
#     -DCMAKE_TOOLCHAIN_FILE="$VCPKG_ROOT/scripts/buildsystems/vcpkg.cmake" \
#     -DCMAKE_BUILD_TYPE=RelWithDebInfo
#   cmake --build air/build -j$(nproc)
#   ctest --test-dir air/build --output-on-failure
#
# Parallel to runtime/. Does not depend on runtime/. Shares no code.

cmake_minimum_required(VERSION 3.21)
project(retrovue_air_vnext LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

find_package(GTest CONFIG REQUIRED)
find_package(Threads REQUIRED)
find_package(Protobuf CONFIG REQUIRED)
find_package(gRPC CONFIG REQUIRED)

set(AIR_VNEXT_ROOT "${CMAKE_CURRENT_SOURCE_DIR}")

# ---- Proto + gRPC code generation (air_control.proto) ----
set(AIR_PROTO_FILE ${AIR_VNEXT_ROOT}/protos/air_control.proto)
set(AIR_PROTO_SRCS ${CMAKE_CURRENT_BINARY_DIR}/air_control.pb.cc)
set(AIR_PROTO_HDRS ${CMAKE_CURRENT_BINARY_DIR}/air_control.pb.h)
set(AIR_GRPC_SRCS  ${CMAKE_CURRENT_BINARY_DIR}/air_control.grpc.pb.cc)
set(AIR_GRPC_HDRS  ${CMAKE_CURRENT_BINARY_DIR}/air_control.grpc.pb.h)

# Resolve the gRPC C++ plugin (vcpkg exposes it as an imported target).
if(TARGET gRPC::grpc_cpp_plugin)
  set(AIR_GRPC_PLUGIN_EXE "$<TARGET_FILE:gRPC::grpc_cpp_plugin>")
else()
  find_program(AIR_GRPC_CPP_PLUGIN_EXE grpc_cpp_plugin REQUIRED)
  set(AIR_GRPC_PLUGIN_EXE "${AIR_GRPC_CPP_PLUGIN_EXE}")
endif()

add_custom_command(
  OUTPUT ${AIR_PROTO_SRCS} ${AIR_PROTO_HDRS} ${AIR_GRPC_SRCS} ${AIR_GRPC_HDRS}
  COMMAND "${CMAKE_COMMAND}" -E make_directory "${CMAKE_CURRENT_BINARY_DIR}"
  COMMAND "$<TARGET_FILE:protobuf::protoc>"
    --grpc_out=${CMAKE_CURRENT_BINARY_DIR}
    --cpp_out=${CMAKE_CURRENT_BINARY_DIR}
    -I ${AIR_VNEXT_ROOT}/protos
    --plugin=protoc-gen-grpc=${AIR_GRPC_PLUGIN_EXE}
    ${AIR_PROTO_FILE}
  DEPENDS ${AIR_PROTO_FILE}
  COMMENT "Generating C++ from ${AIR_PROTO_FILE}"
)

add_library(air_vnext_proto STATIC
  ${AIR_PROTO_SRCS}
  ${AIR_GRPC_SRCS}
)
target_include_directories(air_vnext_proto PUBLIC ${CMAKE_CURRENT_BINARY_DIR})
target_link_libraries(air_vnext_proto PUBLIC
  protobuf::libprotobuf
  gRPC::grpc++
)

# ---- FFmpeg static libs (reused from runtime/third_party; no code coupling) ----
set(FFMPEG_ROOT "${AIR_VNEXT_ROOT}/../runtime/third_party/ffmpeg/install")
set(FFMPEG_INCLUDE_DIR "${FFMPEG_ROOT}/include")
set(FFMPEG_LIB_DIR "${FFMPEG_ROOT}/lib")

find_library(FFMPEG_avformat   NAMES libavformat.a   PATHS "${FFMPEG_LIB_DIR}" NO_DEFAULT_PATH REQUIRED)
find_library(FFMPEG_avcodec    NAMES libavcodec.a    PATHS "${FFMPEG_LIB_DIR}" NO_DEFAULT_PATH REQUIRED)
find_library(FFMPEG_swresample NAMES libswresample.a PATHS "${FFMPEG_LIB_DIR}" NO_DEFAULT_PATH REQUIRED)
find_library(FFMPEG_swscale    NAMES libswscale.a    PATHS "${FFMPEG_LIB_DIR}" NO_DEFAULT_PATH REQUIRED)
find_library(FFMPEG_avutil     NAMES libavutil.a     PATHS "${FFMPEG_LIB_DIR}" NO_DEFAULT_PATH REQUIRED)

# x264: reused from runtime/third_party. Static ffmpeg was built with x264
# encoder support, so libavcodec.a has unresolved x264 symbols.
set(X264_ROOT "${AIR_VNEXT_ROOT}/../runtime/third_party/x264/install")
find_library(X264_LIB NAMES libx264.a libx264.so PATHS "${X264_ROOT}/lib" NO_DEFAULT_PATH REQUIRED)

# ---- Core library: source production, normalization, preview storage ----
add_library(air_vnext STATIC
  src/pad_source_producer.cpp
  src/identity_normalizer.cpp
  src/preview_buffer.cpp
  src/synthetic_source_producer.cpp
  src/standard_normalizer.cpp
  src/file_source_producer.cpp
  src/mpeg_ts_encoder.cpp
  src/socket_emitter.cpp
  src/egress_pacer.cpp
  src/air_session.cpp
  src/grpc_service.cpp
)

target_include_directories(air_vnext PUBLIC
  "${AIR_VNEXT_ROOT}/include"
  "${FFMPEG_INCLUDE_DIR}"
)

# Static FFmpeg link order: high-level to low-level. System deps needed
# for a fully-static FFmpeg build (pthread, m, dl, z). If additional
# transitive deps (bz2, lzma) surface at link time, add here.
target_link_libraries(air_vnext PUBLIC
  air_vnext_proto
  gRPC::grpc++
  ${FFMPEG_avformat}
  ${FFMPEG_avcodec}
  ${FFMPEG_swresample}
  ${FFMPEG_swscale}
  ${FFMPEG_avutil}
  ${X264_LIB}
  Threads::Threads
  m
  dl
  z
  lzma
  bz2
  drm
)

# ---- Contract tests ----
enable_testing()

add_executable(air_vnext_contract_tests
  tests/contracts/pad_preview_slice_test.cpp
  tests/contracts/cadence_and_src_test.cpp
  tests/contracts/promotion_test.cpp
  tests/contracts/file_decode_test.cpp
  tests/contracts/encoder_smoke_test.cpp
  tests/contracts/socket_emit_integration_test.cpp
  tests/contracts/egress_pacer_test.cpp
  tests/contracts/grpc_start_stop_integration_test.cpp
)

target_link_libraries(air_vnext_contract_tests PRIVATE
  air_vnext
  gRPC::grpc++
  GTest::gtest
  GTest::gtest_main
)

# ---- Test fixtures: real media assets from /opt/retrovue/assets ----
# SampleA / SampleB: 720x480 H.264 at 30000/1001, AAC 48kHz stereo.
# Paths injected as compile definitions so tests can locate them without
# environment setup. Override at runtime via AIR_VNEXT_TEST_MEDIA env.
set(AIR_VNEXT_SAMPLE_A "/opt/retrovue/assets/SampleA.mp4")
set(AIR_VNEXT_SAMPLE_B "/opt/retrovue/assets/SampleB.mp4")

target_compile_definitions(air_vnext_contract_tests PRIVATE
  AIR_VNEXT_SAMPLE_A_PATH="${AIR_VNEXT_SAMPLE_A}"
  AIR_VNEXT_SAMPLE_B_PATH="${AIR_VNEXT_SAMPLE_B}"
)

include(GoogleTest)
gtest_discover_tests(air_vnext_contract_tests)

# ---- Runnable binary: retrovue_air_vnext ----
# Minimal binary: --input <file> --listen <port>. Accepts one TCP client,
# emits the file as MPEG-TS through the proven pipeline until EOF.
add_executable(retrovue_air_vnext
  src/main.cpp
)
target_link_libraries(retrovue_air_vnext PRIVATE air_vnext gRPC::grpc++)
