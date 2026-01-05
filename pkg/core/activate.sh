#!/bin/bash
# Retrovue Virtual Environment Activation Script
# IMPORTANT: Use 'source activate.sh' or '. activate.sh' (not './activate.sh')
# This ensures activation persists in your current shell session.

# Check if script is being sourced (not executed directly)
if [ "${BASH_SOURCE[0]}" = "${0}" ]; then
    echo "Error: This script must be sourced, not executed directly."
    echo ""
    echo "Use:"
    echo "  source activate.sh"
    echo "  # or"
    echo "  . activate.sh"
    echo ""
    echo "NOT:"
    echo "  ./activate.sh"
    exit 1
fi

# Check if venv exists
if [ ! -d "./venv" ]; then
    echo "Error: Virtual environment not found at ./venv"
    echo ""
    echo "Please create it first with Python 3.12:"
    echo "  python3.12 -m venv venv"
    echo ""
    echo "If Python 3.12 is not installed, install it first:"
    echo "  sudo apt update"
    echo "  sudo apt install software-properties-common"
    echo "  sudo add-apt-repository ppa:deadsnakes/ppa"
    echo "  sudo apt update"
    echo "  sudo apt install python3.12 python3.12-venv python3.12-dev"
    return 1 2>/dev/null || exit 1
fi

# Check if activate script exists
if [ ! -f "./venv/bin/activate" ]; then
    echo "Error: Virtual environment activation script not found at ./venv/bin/activate"
    echo "The venv directory exists but appears to be incomplete."
    echo "Please recreate it with Python 3.12:"
    echo "  rm -rf venv"
    echo "  python3.12 -m venv venv"
    return 1 2>/dev/null || exit 1
fi

echo "Activating Retrovue virtual environment..."
source ./venv/bin/activate

# Verify activation worked
if [ -z "$VIRTUAL_ENV" ]; then
    echo "Error: Failed to activate virtual environment"
    return 1 2>/dev/null || exit 1
fi

# Check Python version
PYTHON_VERSION=$(python --version 2>&1 | cut -d' ' -f2 | cut -d'.' -f1,2)
REQUIRED_VERSION="3.12"
if [ "$(printf '%s\n' "$REQUIRED_VERSION" "$PYTHON_VERSION" | sort -V | head -n1)" != "$REQUIRED_VERSION" ]; then
    echo "Warning: This project requires Python >=3.12, but venv is using Python $PYTHON_VERSION"
    echo ""
    echo "Please recreate the venv with Python 3.12:"
    echo "  deactivate"
    echo "  rm -rf venv"
    echo "  python3.12 -m venv venv"
    echo "  source activate.sh"
    return 1 2>/dev/null || exit 1
fi

echo "Virtual environment activated! You can now run:"
echo ""
echo "To install retrovue in editable mode:"
echo "  pip install -e ."
echo ""
echo "Then you can use:"
echo "  retrovue --help"
echo "  python run_server.py"
echo ""
echo "Note: If you haven't installed the package yet, use:"
echo "  python -m retrovue.cli.main --help"

