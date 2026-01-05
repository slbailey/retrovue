#!/usr/bin/env python3
"""
VLC Playback Test Script

This script provides instructions and automation for testing HLS playback
in VLC Media Player.
"""

import subprocess
import sys
from pathlib import Path
from urllib.parse import urljoin


def check_vlc_installation():
    """Check if VLC is installed and available."""
    print("🔍 Checking VLC installation...")
    
    try:
        # Try to get VLC version
        result = subprocess.run(["vlc", "--version"], capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            version_line = result.stdout.split('\n')[0]
            print(f"✅ VLC found: {version_line}")
            return True
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    
    # Try alternative VLC commands
    vlc_commands = ["vlc", "vlc.exe", "/Applications/VLC.app/Contents/MacOS/VLC"]
    for cmd in vlc_commands:
        try:
            result = subprocess.run([cmd, "--version"], capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                print(f"✅ VLC found: {cmd}")
                return True
        except (subprocess.TimeoutExpired, FileNotFoundError):
            continue
    
    print("❌ VLC not found")
    print("📥 Please install VLC Media Player:")
    print("   - Windows: https://www.videolan.org/vlc/download-windows.html")
    print("   - macOS: https://www.videolan.org/vlc/download-macos.html")
    print("   - Linux: sudo apt install vlc (Ubuntu/Debian)")
    return False

def generate_test_urls():
    """Generate test URLs for different scenarios."""
    base_url = "http://localhost:8080"
    
    urls = {
        "local_playlist": f"{base_url}/channel/1/playlist.m3u8",
        "local_segment": f"{base_url}/channel/1/segment_001.ts",
        "file_playlist": "file:///path/to/playlist.m3u8",  # Placeholder for file-based testing
    }
    
    return urls

def print_vlc_instructions():
    """Print detailed VLC testing instructions."""
    print("\n📺 VLC Testing Instructions")
    print("=" * 50)
    
    urls = generate_test_urls()
    
    print("1. Open VLC Media Player")
    print("2. Go to: Media → Open Network Stream (Ctrl+N)")
    print("3. Enter one of these URLs:")
    print()
    
    for name, url in urls.items():
        print(f"   {name}: {url}")
    
    print()
    print("4. Click 'Play'")
    print("5. Verify playback:")
    print("   ✅ Stream starts immediately")
    print("   ✅ No buffering or stuttering")
    print("   ✅ Timeline shows correct duration")
    print("   ✅ Audio and video are synchronized")

def test_network_connectivity():
    """Test network connectivity to Retrovue server."""
    print("\n🌐 Testing Network Connectivity")
    print("=" * 50)
    
    import requests
    
    base_url = "http://localhost:8080"
    endpoints = [
        "/api/healthz",
        "/channel/1/playlist.m3u8",
    ]
    
    for endpoint in endpoints:
        url = urljoin(base_url, endpoint)
        try:
            response = requests.get(url, timeout=5)
            status = "✅" if response.status_code == 200 else "❌"
            print(f"{status} {url} - Status: {response.status_code}")
        except requests.exceptions.RequestException as e:
            print(f"❌ {url} - Error: {e}")

def create_vlc_playlist_file():
    """Create a VLC playlist file for easy testing."""
    print("\n📄 Creating VLC Playlist File")
    print("=" * 50)
    
    playlist_content = """#EXTM3U
#EXT-X-VERSION:3
#EXT-X-TARGETDURATION:2
#EXT-X-MEDIA-SEQUENCE:0
#EXT-X-PROGRAM-DATE-TIME:2024-01-15T14:30:00.000Z
#EXTINF:2.000,
segment_001.ts
#EXT-X-PROGRAM-DATE-TIME:2024-01-15T14:30:02.000Z
#EXTINF:2.000,
segment_002.ts
#EXT-X-PROGRAM-DATE-TIME:2024-01-15T14:30:04.000Z
#EXTINF:2.000,
segment_003.ts
"""
    
    playlist_file = Path("test_playlist.m3u8")
    playlist_file.write_text(playlist_content)
    
    print(f"✅ Created test playlist: {playlist_file.absolute()}")
    print(f"📺 To test: Open VLC → Media → Open Network Stream → {playlist_file.absolute()}")

def open_vlc_with_url(url: str):
    """Attempt to open VLC with a specific URL."""
    print(f"\n🚀 Opening VLC with URL: {url}")
    print("=" * 50)
    
    if not check_vlc_installation():
        return False
    
    try:
        # Try to open VLC with the URL
        cmd = ["vlc", url]
        print(f"Running: {' '.join(cmd)}")
        
        # Start VLC in background
        process = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print("✅ VLC started in background")
        print("📺 Check VLC window for playback")
        return True
        
    except Exception as e:
        print(f"❌ Failed to start VLC: {e}")
        return False

def main():
    """Main test function."""
    print("🎬 VLC HLS Playback Test")
    print("=" * 50)
    
    # Check VLC installation
    vlc_available = check_vlc_installation()
    
    if not vlc_available:
        print("\n⚠️  VLC is required for this test")
        print("Please install VLC Media Player and run this script again")
        return 1
    
    # Test network connectivity
    test_network_connectivity()
    
    # Print instructions
    print_vlc_instructions()
    
    # Create test playlist file
    create_vlc_playlist_file()
    
    # Ask if user wants to open VLC automatically
    print("\n" + "=" * 50)
    auto_open = input("Open VLC automatically? (y/N): ").lower().strip()
    
    if auto_open in ['y', 'yes']:
        test_url = "http://localhost:8080/channel/1/playlist.m3u8"
        open_vlc_with_url(test_url)
    
    print("\n🎉 VLC test setup complete!")
    print("📺 Follow the instructions above to test HLS playback in VLC")
    
    return 0

if __name__ == "__main__":
    sys.exit(main())

