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

if ! command -v ansible-galaxy &>/dev/null; then
    echo ""
    echo "Error: 'ansible-galaxy' is not on your PATH."
    if [[ "$METHOD" == "pipx" ]]; then
        echo "pipx installs binaries into ~/.local/bin, which isn't on your PATH yet."
        echo "Add it and re-run 'make setup':"
        echo ""
        if [[ -n "${FISH_VERSION:-}" ]] || [[ "$(basename "${SHELL:-}")" == "fish" ]]; then
            echo "    fish_add_path ~/.local/bin"
        else
            echo "    pipx ensurepath   # then start a new shell"
        fi
    fi
    exit 1
fi

echo "Installing required Ansible collections..."
ansible-galaxy collection install -r "$PROJECT_DIR/requirements.yml"

# --- Optional: qrencode (controller-side WireGuard client QR codes) ----------
# `make wg-render` writes <client>.png QR codes under build/<env>/wireguard/
# so you can scan them straight into the WireGuard mobile app. It needs
# `qrencode` on the controller; if it's missing the playbook still renders
# `<client>.conf` and logs a warning, so this is informational only.
if ! command -v qrencode &>/dev/null; then
    echo ""
    echo "Note: 'qrencode' is not installed on this controller."
    echo "      Without it, 'make wg-render' still writes build/<env>/wireguard/<client>.conf"
    echo "      for every WireGuard client, but skips the matching <client>.png QR codes."
    echo "      Install it if you want to onboard phones by scanning a QR:"
    echo ""
    if command -v dnf &>/dev/null; then
        echo "    sudo dnf install qrencode"
    elif command -v apt &>/dev/null; then
        echo "    sudo apt install qrencode"
    elif command -v pacman &>/dev/null; then
        echo "    sudo pacman -S qrencode"
    elif command -v brew &>/dev/null; then
        echo "    brew install qrencode"
    else
        echo "    (install the 'qrencode' package via your OS package manager)"
    fi
fi

echo ""
echo "Setup complete."
