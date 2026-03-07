#!/bin/bash
# End-to-end smoke test for Retrovue streaming system.
#
# This script performs a complete smoke test of the Retrovue streaming system:
# 1. Starts the FastAPI server
# 2. Requests a stream from /iptv/channel/1.ts for 3 seconds
# 3. Analyzes the output with ffprobe
# 4. Performs hex sync check using Python module
# 5. Exits with appropriate error codes
#
# Usage:
#   ./scripts/smoke_e2e.sh
#   ./scripts/smoke_e2e.sh --server-port 8001 --channel-id 2

set -euo pipefail

# Default parameters
SERVER_PORT=${SERVER_PORT:-8000}
OUTPUT_FILE=${OUTPUT_FILE:-out.ts}
CHANNEL_ID=${CHANNEL_ID:-1}

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --server-port)
            SERVER_PORT="$2"
            shift 2
            ;;
        --channel-id)
            CHANNEL_ID="$2"
            shift 2
            ;;
        --output-file)
            OUTPUT_FILE="$2"
            shift 2
            ;;
        *)
            echo "Unknown option: $1"
            echo "Usage: $0 [--server-port PORT] [--channel-id ID] [--output-file FILE]"
            exit 1
            ;;
    esac
done

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
RESET='\033[0m'

write_color_output() {
    local message="$1"
    local color="${2:-$RESET}"
    echo -e "${color}${message}${RESET}"
}

test_command() {
    command -v "$1" >/dev/null 2>&1
}

start_server() {
    write_color_output "🚀 Starting FastAPI server on port $SERVER_PORT..." "$BLUE"
    
    # Check if Python is available
    if ! test_command python; then
        write_color_output "❌ Python not found in PATH" "$RED"
        exit 1
    fi
    
    # Start ProgramDirector HTTP server in background
    retrovue program-director start --http-port "$SERVER_PORT" &
    SERVER_PID=$!
    
    # Wait for server to start (give it 5 seconds)
    write_color_output "⏳ Waiting for server to start..." "$YELLOW"
    sleep 5
    
    # Check if server is responding
    if curl -s -f "http://127.0.0.1:$SERVER_PORT/" >/dev/null 2>&1; then
        write_color_output "✅ Server started successfully" "$GREEN"
    else
        write_color_output "❌ Failed to connect to server" "$RED"
        kill "$SERVER_PID" 2>/dev/null || true
        wait "$SERVER_PID" 2>/dev/null || true
        exit 1
    fi
}

test_stream_capture() {
    local url="$1"
    local output_file="$2"
    local duration_seconds="${3:-3}"
    
    write_color_output "📡 Capturing stream from $url for $duration_seconds seconds..." "$BLUE"
    
    # Check if curl is available
    if ! test_command curl; then
        write_color_output "❌ curl not found in PATH" "$RED"
        exit 1
    fi
    
    # Remove output file if it exists
    rm -f "$output_file"
    
    # Use curl to capture stream with timeout
    if timeout "$((duration_seconds + 2))" curl -L -o "$output_file" --connect-timeout 10 -m "$duration_seconds" "$url" 2>/dev/null; then
        if [[ ! -f "$output_file" ]]; then
            write_color_output "❌ Output file not created" "$RED"
            exit 1
        fi
        
        local file_size
        file_size=$(stat -f%z "$output_file" 2>/dev/null || stat -c%s "$output_file" 2>/dev/null || echo 0)
        
        if [[ $file_size -eq 0 ]]; then
            write_color_output "❌ Output file is empty" "$RED"
            exit 1
        fi
        
        write_color_output "✅ Stream captured successfully ($file_size bytes)" "$GREEN"
    else
        write_color_output "❌ Failed to capture stream" "$RED"
        exit 1
    fi
}

test_ffprobe() {
    local input_file="$1"
    
    write_color_output "🔍 Analyzing stream with ffprobe..." "$BLUE"
    
    # Check if ffprobe is available
    if ! test_command ffprobe; then
        write_color_output "❌ ffprobe not found in PATH" "$RED"
        exit 1
    fi
    
    # Run ffprobe to get stream information
    local probe_output
    probe_output=$(mktemp)
    local probe_error
    probe_error=$(mktemp)
    
    if ffprobe -v quiet -print_format json -show_streams "$input_file" >"$probe_output" 2>"$probe_error"; then
        write_color_output "📊 Stream Analysis:" "$BLUE"
        
        # Extract stream count
        local stream_count
        stream_count=$(python3 -c "import json, sys; data = json.load(sys.stdin); print(len(data.get('streams', [])))" <"$probe_output")
        write_color_output "Total streams: $stream_count" "$YELLOW"
        
        # Extract and display codec information
        python3 -c "
import json
import sys

with open('$probe_output', 'r') as f:
    data = json.load(f)

for stream in data.get('streams', []):
    codec_type = stream.get('codec_type', 'unknown')
    codec_name = stream.get('codec_name', 'unknown')
    index = stream.get('index', '?')
    
    if codec_type == 'video':
        width = stream.get('width', '?')
        height = stream.get('height', '?')
        bitrate = stream.get('bit_rate', '')
        print(f'  Video Stream {index}: {codec_name} ({width}x{height})')
        if bitrate:
            print(f'    Bitrate: {bitrate} bps')
    elif codec_type == 'audio':
        sample_rate = stream.get('sample_rate', '')
        channels = stream.get('channels', '')
        bitrate = stream.get('bit_rate', '')
        print(f'  Audio Stream {index}: {codec_name}')
        if sample_rate:
            print(f'    Sample Rate: {sample_rate} Hz')
        if channels:
            print(f'    Channels: {channels}')
        if bitrate:
            print(f'    Bitrate: {bitrate} bps')
"
        
        rm -f "$probe_output" "$probe_error"
        write_color_output "✅ FFprobe analysis completed" "$GREEN"
    else
        local error_content
        error_content=$(cat "$probe_error")
        write_color_output "❌ ffprobe failed: $error_content" "$RED"
        rm -f "$probe_output" "$probe_error"
        exit 1
    fi
}

test_hex_sync() {
    local input_file="$1"
    
    write_color_output "🔍 Performing hex sync check..." "$BLUE"
    
    # Check if Python is available
    if ! test_command python3 && ! test_command python; then
        write_color_output "❌ Python not found in PATH" "$RED"
        exit 1
    fi
    
    local python_cmd
    python_cmd=$(command -v python3 || command -v python)
    
    # Create a Python script to perform hex sync check
    local temp_script
    temp_script=$(mktemp)
    
    cat >"$temp_script" <<'PYTHON_SCRIPT'
import sys
import os

def main():
    input_file = sys.argv[1]

    if not os.path.exists(input_file):
        print("❌ Input file not found: " + input_file)
        sys.exit(1)

    with open(input_file, 'rb') as f:
        data = f.read(4096)

    if len(data) < 16:
        print("❌ Insufficient data for analysis")
        sys.exit(1)

    # Inline TS cadence analysis (0x47 sync byte at 188-byte intervals)
    sync_positions = [i for i, b in enumerate(data) if b == 0x47][:10]
    if len(sync_positions) < 2:
        print("❌ Hex sync check failed: insufficient sync bytes")
        sys.exit(1)

    intervals = [sync_positions[i+1] - sync_positions[i] for i in range(len(sync_positions)-1)]
    valid = all(iv == 188 for iv in intervals)

    print("🔍 Hex Sync Analysis:")
    print(f"  Valid: {valid}")
    print(f"  Sync bytes found: {len(sync_positions)}")
    print(f"  Intervals: {intervals}")
    print(f"  First sync at position: {sync_positions[0]}")

    if not valid:
        print("❌ Hex sync check failed")
        sys.exit(1)
    else:
        print("✅ Hex sync check passed")

if __name__ == "__main__":
    main()
PYTHON_SCRIPT
    
    # Run the Python script
    if "$python_cmd" "$temp_script" "$input_file"; then
        write_color_output "✅ Hex sync check completed successfully" "$GREEN"
    else
        write_color_output "❌ Hex sync check failed" "$RED"
        rm -f "$temp_script"
        exit 1
    fi
    
    # Clean up temporary script
    rm -f "$temp_script"
}

cleanup() {
    local server_pid="$1"
    local output_file="$2"
    
    write_color_output "🧹 Cleaning up..." "$BLUE"
    
    # Stop server if it exists
    if [[ -n "$server_pid" ]] && kill -0 "$server_pid" 2>/dev/null; then
        kill "$server_pid" 2>/dev/null || true
        wait "$server_pid" 2>/dev/null || true
    fi
    
    # Remove output file
    rm -f "$output_file"
    
    # Clean up any temporary files
    rm -f ffprobe_* temp_sync_check.py
}

# Main execution
SERVER_PID=""
trap 'cleanup "$SERVER_PID" "$OUTPUT_FILE"' EXIT

write_color_output "🧪 Starting Retrovue E2E Smoke Test" "$BLUE"
write_color_output "=====================================" "$BLUE"

# Step 1: Start FastAPI server
start_server
SERVER_PID=$!

# Step 2: Capture stream
STREAM_URL="http://127.0.0.1:$SERVER_PORT/iptv/channel/$CHANNEL_ID.ts"
test_stream_capture "$STREAM_URL" "$OUTPUT_FILE" 3

# Step 3: Analyze with ffprobe
test_ffprobe "$OUTPUT_FILE"

# Step 4: Perform hex sync check
test_hex_sync "$OUTPUT_FILE"

write_color_output "🎉 All tests passed successfully!" "$GREEN"

exit 0

