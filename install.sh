#!/usr/bin/env bash
# Model Router — Cross-platform installer for Linux/macOS
# Usage: curl -fsSL ... | bash
#    or: ./install.sh

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}╔══════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║   Model Router v1.0.1 — Installer        ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════╝${NC}"
echo ""

# Detect OS
OS="$(uname -s)"
case "$OS" in
    Linux*)  PLATFORM="linux";;
    Darwin*) PLATFORM="macos";;
    *)       echo -e "${RED}Unsupported OS: $OS${NC}"; exit 1;;
esac
echo -e "${YELLOW}Detected: $PLATFORM${NC}"

# Check Python version
PYTHON=""
if command -v python3 &>/dev/null; then
    PY_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
    PY_MAJOR=$(echo "$PY_VERSION" | cut -d. -f1)
    PY_MINOR=$(echo "$PY_VERSION" | cut -d. -f2)
    if [ "$PY_MAJOR" -ge 3 ] && [ "$PY_MINOR" -ge 10 ]; then
        PYTHON="python3"
        echo -e "${GREEN}Python $PY_VERSION ✓${NC}"
    fi
fi

if [ -z "$PYTHON" ]; then
    echo -e "${RED}Python 3.10+ required. Current: ${PY_VERSION:-not found}${NC}"
    echo ""
    echo "Install Python:"
    echo "  Ubuntu/Debian: sudo apt install python3 python3-pip python3-venv"
    echo "  macOS:         brew install python@3.11"
    echo "  Fedora:        sudo dnf install python3 python3-pip"
    exit 1
fi

# Create virtual environment if not exists
VENV_DIR=".venv"
if [ ! -d "$VENV_DIR" ]; then
    echo -e "${YELLOW}Creating virtual environment...${NC}"
    $PYTHON -m venv "$VENV_DIR"
fi

# Activate venv
source "$VENV_DIR/bin/activate"
echo -e "${GREEN}Virtual env activated: $VENV_DIR${NC}"

# Install dependencies
echo -e "${YELLOW}Installing dependencies...${NC}"

# Platform-specific: uvloop on Linux/macOS, winloop is Windows-only
if [ "$PLATFORM" = "macos" ] || [ "$PLATFORM" = "linux" ]; then
    pip install --upgrade pip
    pip install -e ".[all]"
    echo -e "${GREEN}uvloop will be installed automatically on $PLATFORM${NC}"
fi

# Copy config example if config.yaml doesn't exist
if [ ! -f "config.yaml" ] && [ -f "config.example.yaml" ]; then
    cp config.example.yaml config.yaml
    echo -e "${YELLOW}Created config.yaml from example — please add your API keys!${NC}"
fi

echo ""
echo -e "${GREEN}╔══════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║   Installation complete!                 ║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════╝${NC}"
echo ""
echo "Next steps:"
echo "  1. Edit config.yaml — add your API keys"
echo "  2. Run: python -m model_router"
echo "  3. Open: http://127.0.0.1:6060/docs"
echo ""
echo "Or activate venv first:"
echo "  source .venv/bin/activate"
