// AIR vNext — gRPC server binary.
//
// Runs the AirControl service on a configurable listen address. Core is
// the client; AIR is the server. Byte path is carried out-of-band over
// a Unix Domain Socket that Core binds and AIR connects to on StartChannel.
//
// Usage:
//   retrovue_air_vnext --listen 0.0.0.0:50051
//
// Previous TCP-listener flow (--input / --listen <port>) has been retired
// in favour of RPC-driven startup. The input path now comes from the
// StartChannelRequest.

#include <grpcpp/grpcpp.h>
#include <signal.h>

#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <iostream>
#include <memory>
#include <string>

#include "grpc_service.hpp"

namespace {

void Usage(const char* argv0) {
  std::fprintf(stderr,
               "usage: %s --listen <host:port>\n"
               "  --listen  gRPC listen address (e.g. 0.0.0.0:50051)\n",
               argv0);
}

}  // namespace

int main(int argc, char** argv) {
  using namespace retrovue::air;

  std::string listen_addr;

  for (int i = 1; i < argc; ++i) {
    if (std::strcmp(argv[i], "--listen") == 0 && i + 1 < argc) {
      listen_addr = argv[++i];
    } else {
      Usage(argv[0]);
      return 2;
    }
  }
  if (listen_addr.empty()) {
    Usage(argv[0]);
    return 2;
  }

  // SIGPIPE: never kill on consumer disconnect. MSG_NOSIGNAL in SocketEmitter
  // guards send() paths; this guards anything else.
  ::signal(SIGPIPE, SIG_IGN);

  AirControlServiceImpl service;

  grpc::ServerBuilder builder;
  builder.AddListeningPort(listen_addr, grpc::InsecureServerCredentials());
  builder.RegisterService(&service);

  std::unique_ptr<grpc::Server> server = builder.BuildAndStart();
  if (!server) {
    std::cerr << "[air] failed to start gRPC server on " << listen_addr
              << std::endl;
    return 1;
  }
  std::cerr << "[air] gRPC AirControl server on " << listen_addr << std::endl;
  server->Wait();  // blocks until server shuts down (e.g. SIGINT).
  return 0;
}
