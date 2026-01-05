"""
Test to ensure no Qt/PySide references remain in the codebase.
This is a guardrail to prevent Qt from re-entering the codebase.
"""

import subprocess
import sys
from pathlib import Path


class TestNoQtLeft:
    """Test that no Qt/PySide references exist in the codebase."""
    
    def test_no_qt_references(self):
        """Scan the entire repository for banned Qt/PySide terms."""
        repo_root = Path(__file__).parent.parent
        script_path = repo_root / "scripts" / "check_no_qt.py"
        
        # Run the anti-Qt check script
        result = subprocess.run(
            [sys.executable, str(script_path)],
            cwd=repo_root,
            capture_output=True,
            text=True
        )
        
        # The script should exit with code 0 (success) if no Qt references found
        assert result.returncode == 0, (
            f"Qt/PySide references found in codebase!\n"
            f"STDOUT: {result.stdout}\n"
            f"STDERR: {result.stderr}\n"
            f"Retrovue is web-only - no Qt/PySide allowed!"
        )
        
        # Verify the success message is in output
        assert "No banned Qt/PySide references found!" in result.stdout
        assert "Repository is clean - Retrovue remains web-only!" in result.stdout
    
    def test_anti_qt_script_exists(self):
        """Ensure the anti-Qt check script exists and is executable."""
        repo_root = Path(__file__).parent.parent
        script_path = repo_root / "scripts" / "check_no_qt.py"
        
        assert script_path.exists(), "Anti-Qt check script should exist"
        assert script_path.is_file(), "Anti-Qt check script should be a file"
    
    def test_pre_commit_config_exists(self):
        """Ensure pre-commit configuration exists with anti-Qt hooks."""
        repo_root = Path(__file__).parent.parent
        pre_commit_config = repo_root / ".pre-commit-config.yaml"
        
        assert pre_commit_config.exists(), "Pre-commit config should exist"
        
        # Read and verify the config contains anti-Qt hooks
        config_content = pre_commit_config.read_text()
        assert "no-qt-references" in config_content
        assert "check_no_qt.py" in config_content
