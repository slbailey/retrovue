# Retrovue

Retrovue is a multi-component application for simulating broadcast television channels, complete with real-time playout and scheduling. This project combines a Python-based coordinator with a high-performance C++ playback engine.

## Project Structure

This project is a monorepo containing the following components:

```
/
├── assets/         # Test media and other shared assets
├── docs/           # All project documentation
│   ├── air/        # C++ playback engine docs
│   ├── core/       # Python coordinator docs
│   └── standards/  # Documentation standards and templates
├── pkg/
│   ├── air/        # C++ real-time playback engine source
│   └── core/       # Python coordinator and application logic source
├── protos/         # Consolidated Protobuf API definitions
├── scripts/
│   ├── air/        # Scripts specific to the C++ package
│   └── core/       # Scripts specific to the Python package
└── README.md
```

## Start here (docs)

- **System component map**: `docs/ComponentMap.md` (what the key parts are, what they do, and where their interfaces live)
- **Core (Python) docs index**: `docs/core/README.md`
- **Air (C++) docs index**: `docs/air/README.md`

## Getting Started

### Prerequisites

Before you begin, ensure you have the following installed:

- **Python:** 3.9 or higher, with `pip` and `virtualenv`.
- **C++ Compiler:** A modern C++ compiler (e.g., MSVC on Windows, GCC on Linux, Clang on macOS).
- **CMake:** Version 3.20 or higher.
- **vcpkg:** The C++ package manager. Follow the [official vcpkg installation guide](https://vcpkg.io/en/getting-started.html).
- **Protobuf Compiler (`protoc`):** Required for generating code from the `.proto` files.

### Setup & Installation

1.  **Clone the repository:**

    ```bash
    git clone <your-repo-url>
    cd retrovue
    ```

2.  **Set up Python Environment:**
    Create and activate a virtual environment for the Python coordinator.

    ```bash
    # Create the virtual environment
    python -m venv .venv

    # Activate it (Windows)
    .venv\Scripts\activate

    # Activate it (Linux/macOS)
    source .venv/bin/activate
    ```

3.  **Install Python Dependencies:**
    Install the required packages using pip.

    ```bash
    pip install -r pkg/core/requirements.txt
    ```

4.  **Install C++ Dependencies:**
    Use the provided script to install the C++ dependencies via vcpkg.
    ```bash
    # Ensure vcpkg is correctly set up in your environment
    sh pkg/air/INSTALL_VCPKG_PACKAGES.sh
    ```

## How to Build

To build the necessary components, run the build scripts.

_(Note: A unified `scripts/build.sh` script is recommended to orchestrate these steps.)_

1.  **Generate Protobuf Code:**
    Run the `generate_proto.sh` script to create both the C++ and Python gRPC code from the definitions in `/protos`.

    ```bash
    sh scripts/air/generate_proto.sh
    ```

2.  **Build the C++ Application:**
    Use CMake to configure and build the `retrovue_air` application.

    ```bash
    # Configure and build (output under pkg/air/build)
    cmake -S pkg/air -B pkg/air/build -DCMAKE_TOOLCHAIN_FILE="$VCPKG_ROOT/scripts/buildsystems/vcpkg.cmake" -DCMAKE_BUILD_TYPE=RelWithDebInfo
    cmake --build pkg/air/build -j$(nproc)
    ```

## How to Test

To run the test suites for both packages, run the test scripts.

_(Note: A unified `scripts/test.sh` script is recommended.)_

- **Run Core (Python) Tests:**

  ```bash
  pytest pkg/core/tests/
  ```

- **Run Air (C++) Tests:**
  ```bash
  # From the build directory
  cd build
  ctest
  ```
