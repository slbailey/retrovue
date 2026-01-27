# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

RetroVue is a multi-component application for simulating broadcast television channels with real-time playout and scheduling. The system process is `retrovue`. The system only spins up real video processing (ffmpeg) when viewers are actively watching.

## Build and Test Commands

### Python Core (pkg/core/)

```bash
# Install dependencies
pip install -r pkg/core/requirements.txt

# Run all tests
pytest pkg/core/tests/

# Run a single test file
pytest pkg/core/tests/contracts/test_source_add_contract.py -vv

# Run contract tests only
pytest pkg/core/tests/contracts -vv

# Lint
ruff check pkg/core/src/
mypy pkg/core/src/
```

### Internal Playout Engine (pkg/air/)

```bash
# Install vcpkg dependencies
sh scripts/air/INSTALL_VCPKG_PACKAGES.sh

# Generate protobuf code
sh scripts/air/generate_proto.sh

# Configure and build
cmake -S pkg/air -B build -DCMAKE_TOOLCHAIN_FILE="$VCPKG_ROOT/scripts/buildsystems/vcpkg.cmake" -DCMAKE_BUILD_TYPE=RelWithDebInfo
cmake --build build -j$(nproc)

# Run tests
ctest --test-dir build --output-on-failure

# Note: The playout engine is an internal component and should not be run independently
```

### Database Setup

Tests require PostgreSQL. Run migrations before testing:
```bash
cd pkg/core && alembic upgrade head
```

## Architecture

### Two-Package Structure

- **Core (Python)**: Orchestration, scheduling, state management, CLI. Entry point: `retrovue` CLI via `pkg/core/src/retrovue/cli/main.py`
- **Internal playout engine (C++)**: Real-time decode/render/playout engine. Communicates with Core via gRPC defined in `protos/playout.proto`

### Core Runtime Flow

1. **MasterClock** - Single authoritative time source for scheduling and playout
2. **ScheduleService** - Answers "what should be airing now?" for each channel
3. **ChannelManager** - Per-channel orchestration; starts/stops Producers; calls the internal playout engine via gRPC
4. **ProgramDirector** - The control plane inside RetroVue; system-wide coordination and policy (normal/emergency modes)
5. **AsRunLogger** - Records what actually aired for compliance

### Internal Playout Engine Pipeline

1. **PlayoutEngine** (gRPC control plane) - Channel lifecycle via StartChannel/UpdatePlan/StopChannel
2. **Producers** - Decode assets using FFmpeg/libav
3. **FrameRingBuffer** - Lock-free staging between decode and render
4. **Renderer** - Converts frames to renderable output
5. **MPEG-TS sinks** - Emit continuous streams with pacing/backpressure

### Domain Entities (Core)

Key models in `pkg/core/src/retrovue/domain/`: Source, Collection, Asset, Enricher, Channel, Program, Zone, SchedulePlan, ScheduleDay, Playlist, PlaylogEvent

## Contract-First Development

This codebase uses contract-first development. For every CLI command or usecase:

1. Update the contract doc in `docs/core/contracts/resources/` first
2. Write/update contract tests to match documented behavior
3. Then modify application code

Contract tests exist in pairs:
- `<command>_contract.py` - CLI behavior (args, exit codes, output)
- `<command>_data_contract.py` - Database state changes

## Key Documentation Entry Points

- `docs/ComponentMap.md` - Cross-repo component list and interfaces
- `docs/core/README.md` - Core (Python) documentation index
- `docs/air/README.md` - Internal playout engine (C++) documentation index
- `docs/core/architecture/ArchitectureOverview.md` - System mental model
- `docs/core/contracts/resources/README.md` - CLI/usecase contract index

## Code Layout Conventions

### Python (Core)
- Source: `pkg/core/src/retrovue/`
- CLI commands: `pkg/core/src/retrovue/cli/commands/`
- Usecases: `pkg/core/src/retrovue/usecases/`
- Domain models: `pkg/core/src/retrovue/domain/`
- Tests: `pkg/core/tests/`

### C++ (Internal playout engine)
- Public headers: `pkg/air/include/retrovue/<module>/`
- Implementation: `pkg/air/src/<module>/`
- Tests: `pkg/air/tests/`
- Namespaces mirror directory structure (e.g., `retrovue::buffer`)

## Shell Environment

- Development uses WSL/Ubuntu with bash
- Scripts use `.sh` extension and should be POSIX-compliant where possible
- All scripts must be executable: `chmod +x script.sh`
