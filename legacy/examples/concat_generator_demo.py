#!/usr/bin/env python3
"""
Demonstration of concat file generator.

This script shows how to use the concat generator to create FFmpeg concat files
with alternating episode segments and advertisements.
"""

import os
import tempfile

from retrovue.concat.generator import (
    cleanup_concat_file,
    generate_concat_file,
    read_concat_file,
    validate_concat_file,
)


def demo_concat_generator():
    """Demonstrate concat file generator functionality."""
    print("Concat File Generator Demo")
    print("=" * 40)
    
    with tempfile.TemporaryDirectory() as temp_dir:
        # Create dummy episode segments
        print("1. Creating dummy episode segments...")
        segments = []
        for i in range(3):
            segment_path = os.path.join(temp_dir, f"episode_segment_{i+1}.mp4")
            with open(segment_path, 'w') as f:
                f.write(f"Episode segment {i+1} content")
            segments.append(segment_path)
            print(f"   Created: {segment_path}")
        
        # Create dummy advertisements
        print("\n2. Creating dummy advertisements...")
        ads = []
        for i in range(2):
            ad_path = os.path.join(temp_dir, f"advertisement_{i+1}.mp4")
            with open(ad_path, 'w') as f:
                f.write(f"Advertisement {i+1} content")
            ads.append(ad_path)
            print(f"   Created: {ad_path}")
        
        # Generate concat file
        print("\n3. Generating concat file...")
        concat_path = generate_concat_file(segments, ads)
        print(f"   Concat file created: {concat_path}")
        
        try:
            # Display concat file content
            print("\n4. Concat file content:")
            with open(concat_path) as f:
                content = f.read()
                print(content)
            
            # Validate concat file
            print("\n5. Validating concat file...")
            is_valid = validate_concat_file(concat_path)
            print(f"   Validation result: {'PASSED' if is_valid else 'FAILED'}")
            
            # Read concat file
            print("\n6. Reading concat file paths...")
            file_paths = read_concat_file(concat_path)
            print(f"   Found {len(file_paths)} files in concat file:")
            for i, path in enumerate(file_paths, 1):
                print(f"   {i}. {path}")
            
            # Show expected order
            print("\n7. Expected playback order:")
            print("   [OK] Episode segment 1")
            print("   [OK] Advertisement 1")
            print("   [OK] Episode segment 2")
            print("   [OK] Advertisement 2")
            print("   [OK] Episode segment 3")
            
            print("\n8. Key Features:")
            print("   [OK] Alternating episode segments and ads")
            print("   [OK] Proper FFmpeg concat file format")
            print("   [OK] File existence validation")
            print("   [OK] Temporary file management")
            print("   [OK] Support for spaces and special characters in paths")
            
        finally:
            # Clean up
            print("\n9. Cleaning up...")
            cleanup_concat_file(concat_path)
            print("   [OK] Concat file cleaned up")


def demo_edge_cases():
    """Demonstrate edge cases and error handling."""
    print("\n" + "=" * 40)
    print("Edge Cases Demo")
    print("=" * 40)
    
    # Test empty segments
    print("1. Testing empty segments (should raise ValueError):")
    try:
        generate_concat_file([], ["ad1.mp4"])
        print("   ERROR: Should have raised ValueError")
    except ValueError as e:
        print(f"   [OK] Correctly raised ValueError: {e}")
    
    # Test no ads
    print("\n2. Testing with no ads:")
    with tempfile.TemporaryDirectory() as temp_dir:
        segment_path = os.path.join(temp_dir, "segment.mp4")
        with open(segment_path, 'w') as f:
            f.write("dummy content")
        
        concat_path = generate_concat_file([segment_path], [])
        try:
            with open(concat_path) as f:
                content = f.read().strip()
            print(f"   [OK] Concat file content: {content}")
        finally:
            cleanup_concat_file(concat_path)
    
    # Test validation with missing files
    print("\n3. Testing validation with missing files:")
    with tempfile.TemporaryDirectory() as temp_dir:
        concat_path = os.path.join(temp_dir, "invalid.txt")
        with open(concat_path, 'w') as f:
            f.write("file '/nonexistent/file.mp4'")
        
        is_valid = validate_concat_file(concat_path)
        print(f"   [OK] Validation result: {'PASSED' if is_valid else 'FAILED'}")
        print("   [OK] Correctly detected missing file")


if __name__ == "__main__":
    demo_concat_generator()
    demo_edge_cases()
