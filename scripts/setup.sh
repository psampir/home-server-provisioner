#!/usr/bin/env bash
#
# Install Ansible, ansible-lint, and required collections.
# Supports Homebrew and pipx on both macOS and Linux.
#
# Usage:
#   ./scripts/setup.sh          Auto-detect available package manager
#   ./scripts/setup.sh brew     Use Homebrew
#   ./scripts/setup.sh pipx     Use pipx

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

install_with_brew() {
    if ! command -v brew &>/dev/null; then
        echo "Error: Homebrew is not installed."
        echo "Install it from https://brew.sh"
        exit 1
    fi
    echo "Installing Ansible and ansible-lint via Homebrew..."
    brew install ansible ansible-lint
}

install_with_pipx() {
    if ! command -v pipx &>/dev/null; then
        echo "Error: pipx is not installed."
        echo "Install it with: https://pipx.pypa.io/stable/installation/"
        exit 1
    fi
    echo "Installing Ansible and ansible-lint via pipx..."
    pipx install --include-deps ansible
    pipx install ansible-lint
}

METHOD="${1:-}"

if [[ -z "$METHOD" ]]; then
    if command -v brew &>/dev/null; then
        METHOD="brew"
    elif command -v pipx &>/dev/null; then
        METHOD="pipx"
    else
        echo "Error: Neither Homebrew nor pipx found."
        echo "Install one of them first, then re-run: ./scripts/setup.sh [brew|pipx]"
        exit 1
    fi
    echo "Auto-detected: $METHOD"
fi

case "$METHOD" in
    brew) install_with_brew ;;
    pipx) install_with_pipx ;;
    *)
        echo "Usage: $0 [brew|pipx]"
        exit 1
        ;;
esac

echo "Installing required Ansible collections..."
ansible-galaxy collection install -r "$PROJECT_DIR/requirements.yml"

echo ""
echo "Setup complete."
