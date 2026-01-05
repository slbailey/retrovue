"""
CLI test utilities for RetroVue contract tests.

Provides helper functions for testing CLI commands using Typer's CliRunner.
"""

from __future__ import annotations

import subprocess
import sys


def run_cli(args: list[str]) -> tuple[int, str, str]:
    """
    Run the RetroVue CLI with the given arguments.
    
    Args:
        args: List of command line arguments (e.g., ['source', 'list', '--help'])
        
    Returns:
        Tuple of (exit_code, stdout, stderr)
    """
    # Import the actual CLI app
    # Use Typer's built-in testing mechanism
    from typer.testing import CliRunner

    from retrovue.cli.main import app
    
    runner = CliRunner()
    result = runner.invoke(app, args)
    
    return result.exit_code, result.stdout, result.stderr


def run_cli_subprocess(args: list[str]) -> tuple[int, str, str]:
    """
    Alternative CLI runner using subprocess (fallback if Typer testing fails).
    
    Args:
        args: List of command line arguments
        
    Returns:
        Tuple of (exit_code, stdout, stderr)
    """
    try:
        # Use the retrovue console script
        cmd = [sys.executable, "-m", "retrovue.cli.main"] + args
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return 1, "", "Command timed out"
    except Exception as e:
        return 1, "", str(e)