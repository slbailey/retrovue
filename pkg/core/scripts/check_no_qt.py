#!/usr/bin/env python3
"""
Anti-Qt guardrail script for Retrovue.
Scans the repository for banned Qt/PySide terms and fails if found.
"""

import re
import sys
from pathlib import Path

# Banned terms that should not appear in the codebase
BANNED_TERMS = [
    r'\bPySide6\b',
    r'\bPyQt6\b', 
    r'\bqtpy\b',
    r'\bQtCore\b',
    r'\bQtGui\b',
    r'\bQtWidgets\b',
    r'\bQWidget\b',
    r'\bQMainWindow\b',
    r'\bQApplication\b',
    r'\.ui\b',
    r'\.qrc\b',
    r'qrc_',
]

# Directories to exclude from scanning
EXCLUDE_DIRS = {
    '.git', 'venv', '.venv', 'node_modules', 'dist', 'build', 
    '__pycache__', '.pytest_cache', '.mypy_cache'
}

# Files to exclude from scanning
EXCLUDE_FILES = {
    'REPORT.md',  # Our own report file
    'CHANGELOG.md',  # Changelog files
    'check_no_qt.py',  # This script itself
    'test_no_qt_left.py',  # Anti-Qt test
    'test_architecture_guard.py',  # Architecture guard test
}

def should_scan_file(file_path: Path) -> bool:
    """Determine if a file should be scanned."""
    # Skip excluded files
    if file_path.name in EXCLUDE_FILES:
        return False
    
    # Skip excluded directories
    for part in file_path.parts:
        if part in EXCLUDE_DIRS:
            return False
    
    # Only scan text files
    if file_path.suffix not in {'.py', '.md', '.txt', '.yml', '.yaml', '.toml', '.json'}:
        return False
    
    return True

def scan_file(file_path: Path) -> list:
    """Scan a single file for banned terms."""
    violations = []
    
    try:
        with open(file_path, encoding='utf-8', errors='ignore') as f:
            content = f.read()
            lines = content.splitlines()
            
            for line_num, line in enumerate(lines, 1):
                for pattern in BANNED_TERMS:
                    if re.search(pattern, line, re.IGNORECASE):
                        violations.append({
                            'file': str(file_path),
                            'line': line_num,
                            'pattern': pattern,
                            'content': line.strip()
                        })
    except Exception as e:
        print(f"Warning: Could not scan {file_path}: {e}")
    
    return violations

def main():
    """Main function to scan repository for banned Qt terms."""
    repo_root = Path(__file__).parent.parent
    violations = []
    
    print("Scanning repository for banned Qt/PySide references...")
    
    # Scan all files in the repository
    for file_path in repo_root.rglob('*'):
        if file_path.is_file() and should_scan_file(file_path):
            file_violations = scan_file(file_path)
            violations.extend(file_violations)
    
    if violations:
        print("\nBANNED Qt/PySide REFERENCES FOUND:")
        print("=" * 60)
        
        for violation in violations:
            print(f"File: {violation['file']}")
            print(f"Line: {violation['line']}")
            print(f"Pattern: {violation['pattern']}")
            print(f"Content: {violation['content']}")
            print("-" * 40)
        
        print(f"\nFound {len(violations)} violations!")
        print("\nRetrovue is now web-only. Qt/PySide references are not allowed.")
        print("Please remove these references and use web technologies instead.")
        
        sys.exit(1)
    else:
        print("No banned Qt/PySide references found!")
        print("Repository is clean - Retrovue remains web-only!")

if __name__ == '__main__':
    main()
