#!/usr/bin/env python3
"""
Test runner for MasterClock tests.

This script runs all MasterClock tests and provides detailed output.
"""

import os
import subprocess
import sys
from pathlib import Path


def run_tests():
    """Run all MasterClock tests."""
    # Get the project root directory
    project_root = Path(__file__).parent.parent.parent
    os.chdir(project_root)
    
    # Test files to run
    test_files = [
        "tests/runtime/test_clock.py",
        "tests/runtime/test_clock_performance.py"
    ]
    
    print("Running MasterClock tests...")
    print("=" * 50)
    
    all_passed = True
    
    for test_file in test_files:
        print(f"\nRunning {test_file}...")
        print("-" * 30)
        
        try:
            result = subprocess.run([
                sys.executable, "-m", "pytest", test_file, "-v", "--tb=short"
            ], capture_output=True, text=True)
            
            print(result.stdout)
            if result.stderr:
                print("STDERR:", result.stderr)
            
            if result.returncode != 0:
                all_passed = False
                print(f"❌ {test_file} failed")
            else:
                print(f"✅ {test_file} passed")
                
        except Exception as e:
            print(f"❌ Error running {test_file}: {e}")
            all_passed = False
    
    print("\n" + "=" * 50)
    if all_passed:
        print("✅ All MasterClock tests passed!")
        return 0
    else:
        print("❌ Some MasterClock tests failed!")
        return 1


def run_specific_test(test_name):
    """Run a specific test by name."""
    project_root = Path(__file__).parent.parent.parent
    os.chdir(project_root)
    
    print(f"Running specific test: {test_name}")
    print("=" * 50)
    
    try:
        result = subprocess.run([
            sys.executable, "-m", "pytest", f"tests/runtime/test_clock.py::{test_name}", "-v", "--tb=short"
        ], capture_output=True, text=True)
        
        print(result.stdout)
        if result.stderr:
            print("STDERR:", result.stderr)
        
        return result.returncode
        
    except Exception as e:
        print(f"❌ Error running test {test_name}: {e}")
        return 1


def run_performance_tests():
    """Run only performance tests."""
    project_root = Path(__file__).parent.parent.parent
    os.chdir(project_root)
    
    print("Running MasterClock performance tests...")
    print("=" * 50)
    
    try:
        result = subprocess.run([
            sys.executable, "-m", "pytest", "tests/runtime/test_clock_performance.py", "-v", "--tb=short"
        ], capture_output=True, text=True)
        
        print(result.stdout)
        if result.stderr:
            print("STDERR:", result.stderr)
        
        return result.returncode
        
    except Exception as e:
        print(f"❌ Error running performance tests: {e}")
        return 1


if __name__ == "__main__":
    if len(sys.argv) > 1:
        if sys.argv[1] == "--performance":
            exit_code = run_performance_tests()
        elif sys.argv[1].startswith("--test="):
            test_name = sys.argv[1].split("=", 1)[1]
            exit_code = run_specific_test(test_name)
        else:
            print("Usage: python run_clock_tests.py [--performance] [--test=test_name]")
            exit_code = 1
    else:
        exit_code = run_tests()
    
    sys.exit(exit_code)
