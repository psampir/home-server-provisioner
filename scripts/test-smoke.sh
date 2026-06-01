#!/usr/bin/env bash
#
# End-to-end smoke test for the test environment.
#
# Brings up the auto-generated WireGuard client config on the controller
# (this machine), verifies that all three layers of the hub stack work
# together, then tears the tunnel down. Idempotent: trap-based cleanup
# fires on any exit path (success, failure, Ctrl-C).
#
# What this verifies:
#   1. WireGuard handshake   - controller (10.10.0.20) reaches hub (10.10.0.1)
#   2. Peer routing via hub  - hub forwards to managed peer (10.10.0.2)
#   3. dnsmasq on the hub    - `whoami.home` resolves to 10.10.0.1
#   4. Caddy on the hub      - TLS handshake (`tls internal`) + reverse proxy
#   5. Backend reachability  - whoami container on hsp-app answers
#
# Requires:
#   - sudo (for wg-quick up/down and writing to /etc/wireguard/)
#   - a successful `make test-provision` run (creates the WG client config)
#   - `wireguard-tools` package (provides wg-quick)
#
# Usage:
#   ./scripts/test-smoke.sh
#   make test-smoke
#
# Exit code is the count of failed checks (0 = all green).

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

WG_IFACE="wg-test"
WG_SRC="$PROJECT_DIR/build/wireguard/test-controller.conf"
WG_DST="/etc/wireguard/${WG_IFACE}.conf"

HUB_IP="10.10.0.1"
PEER_IP="10.10.0.2"
SITE_URL="https://whoami.home/"

FAILS=0
TUNNEL_UP=0

# --- Colour helpers ---
if [[ -t 1 ]]; then
    GREEN='\033[0;32m'; RED='\033[0;31m'; YELLOW='\033[1;33m'; RESET='\033[0m'
else
    GREEN=''; RED=''; YELLOW=''; RESET=''
fi

step()    { printf "${YELLOW}==> %s${RESET}\n" "$*"; }
ok()      { printf "${GREEN}✓ %s${RESET}\n" "$*"; }
fail()    { printf "${RED}✗ %s${RESET}\n" "$*"; FAILS=$((FAILS + 1)); }

cleanup() {
    if (( TUNNEL_UP )); then
        step "Cleaning up: bringing $WG_IFACE down"
        sudo wg-quick down "$WG_IFACE" >/dev/null 2>&1 || true
    fi
    if [[ -f "$WG_DST" ]]; then
        sudo rm -f "$WG_DST"
    fi
    if (( FAILS == 0 )); then
        printf "\n${GREEN}All smoke-test checks passed.${RESET}\n"
    else
        printf "\n${RED}%d check(s) failed.${RESET}\n" "$FAILS"
    fi
    exit "$FAILS"
}
trap cleanup EXIT INT TERM

# --- Pre-flight ---
if [[ ! -r "$WG_SRC" ]]; then
    fail "WireGuard client config not found at $WG_SRC."
    echo "    Run 'make test-wg-render' first - it generates client .conf + QR"
    echo "    under build/wireguard/ (decoupled from 'make test-provision')."
    exit 1
fi

if ! command -v wg-quick >/dev/null 2>&1; then
    fail "wg-quick not installed. Install wireguard-tools (sudo dnf install wireguard-tools)."
    exit 1
fi

# Refuse to clobber an already-active interface of the same name.
if ip link show "$WG_IFACE" >/dev/null 2>&1; then
    fail "Interface $WG_IFACE already exists. Run: sudo wg-quick down $WG_IFACE"
    exit 1
fi

# --- 1. Bring the tunnel up ---
step "Installing test client config to $WG_DST"
sudo install -m 600 "$WG_SRC" "$WG_DST"

step "Bringing tunnel $WG_IFACE up"
if sudo wg-quick up "$WG_IFACE"; then
    TUNNEL_UP=1
    ok "Tunnel $WG_IFACE is up"
else
    fail "wg-quick up failed"
    exit "$FAILS"
fi

# Give the kernel a moment to install routes and the WG handshake to complete.
sleep 1

# --- 2. Hub reachable ---
step "Pinging hub ($HUB_IP)"
if ping -c2 -W2 "$HUB_IP" >/dev/null 2>&1; then
    ok "Hub responds to ICMP"
else
    fail "Hub did not respond - WG handshake or routing broken"
fi

# --- 3. Peer reachable (via hub forwarding) ---
step "Pinging managed peer ($PEER_IP, routed via hub)"
if ping -c2 -W2 "$PEER_IP" >/dev/null 2>&1; then
    ok "Peer responds - hub is forwarding between peers"
else
    fail "Peer unreachable - check ip_forward + UFW route allow on the hub"
fi

# --- 4. DNS via dnsmasq on the hub ---
step "Resolving whoami.home via tunnel DNS"
if RESOLVED=$(getent hosts whoami.home 2>/dev/null | awk '{print $1; exit}'); then
    if [[ "$RESOLVED" == "$HUB_IP" ]]; then
        ok "whoami.home -> $RESOLVED (hub)"
    else
        fail "whoami.home -> $RESOLVED (expected $HUB_IP)"
    fi
else
    fail "Could not resolve whoami.home - dnsmasq not reachable or extra_hosts missing"
fi

# --- 5. End-to-end HTTPS through Caddy ---
step "Fetching $SITE_URL (TLS via Caddy local CA, proxied to backend)"
if BODY=$(curl --silent --show-error --insecure --max-time 5 "$SITE_URL" 2>&1); then
    # whoami returns plaintext lines like "Hostname: ...", "RemoteAddr: 10.10.0.1:..."
    if grep -q "^Hostname:" <<< "$BODY" && grep -q "RemoteAddr: ${HUB_IP}:" <<< "$BODY"; then
        ok "Caddy terminated TLS and proxied to whoami backend"
        printf "    (backend saw RemoteAddr from %s - request came through the WG tunnel)\n" "$HUB_IP"
    else
        fail "Unexpected response body from $SITE_URL"
        printf "    --- response ---\n%s\n    ----------------\n" "$BODY"
    fi
else
    fail "curl to $SITE_URL failed"
fi

# trap fires cleanup() and exits with $FAILS
