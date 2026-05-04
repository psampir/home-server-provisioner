#!/usr/bin/env bash
#
# Test environment management for home-server-provisioner.
#
# Reads VM definitions from scripts/test-vms.conf and manages
# Incus VMs + Ansible test inventory.
#
# Usage:
#   ./scripts/test-env.sh create   - Launch VMs and generate inventory
#   ./scripts/test-env.sh destroy  - Delete all VMs and clean up inventory
#   ./scripts/test-env.sh status   - Show current VM state
#
# Prerequisites:
#   - incus installed and initialised (see README)
#   - current user is in the 'incus-admin' group
#   - jq (used to parse 'incus list --format json')

set -euo pipefail

# --- Configuration ---

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
VM_CONF="$SCRIPT_DIR/test-vms.conf"
INVENTORY_FILE="$PROJECT_DIR/inventories/test/hosts.yml"

# VM resource defaults (overridable via .env)
VM_CPUS="${VM_CPUS:-2}"
VM_MEMORY="${VM_MEMORY:-2GiB}"
INCUS_IMAGE="${INCUS_IMAGE:-images:debian/13}"

# Bootstrap user created on each VM after launch.
# This simulates the regular user a human would create during a Debian
# netinst install. Configurable via .env so users can match their preferred
# initial username.
BOOTSTRAP_USER="${BOOTSTRAP_USER:-testadmin}"

# All groups the project supports (used to build complete inventory)
ALL_GROUPS="app_servers backup_targets vpn_servers"

# IP wait tuning
IP_WAIT_ATTEMPTS=30   # ~60s @ 2s sleep
IP_WAIT_SLEEP=2

# Agent wait tuning (Incus agent must come up before incus exec works)
AGENT_WAIT_ATTEMPTS=30
AGENT_WAIT_SLEEP=2

# --- Helper functions ---

die() { echo "Error: $1" >&2; exit 1; }

require_cmd() {
    command -v "$1" >/dev/null 2>&1 || die "'$1' is required but not installed."
}

require_cmd incus
require_cmd jq

# Read VM definitions from config, skipping comments and blank lines
read_vms() {
    grep -v '^\s*#' "$VM_CONF" | grep -v '^\s*$'
}

# Find the user's SSH public key
detect_ssh_pubkey() {
    local key=""
    for candidate in "$HOME/.ssh/id_ed25519.pub" "$HOME/.ssh/id_rsa.pub" "$HOME/.ssh/id_ecdsa.pub"; do
        if [[ -f "$candidate" ]]; then
            key="$candidate"
            break
        fi
    done

    if [[ -z "$key" ]]; then
        die "No SSH public key found. Set SSH_PUBKEY_FILE in .env or create a key with ssh-keygen."
    fi

    echo "$key"
}

# Wait for the Incus agent inside the VM to be ready
wait_for_agent() {
    local vm_name="$1"
    local attempts=0
    while [[ $attempts -lt $AGENT_WAIT_ATTEMPTS ]]; do
        if incus exec "$vm_name" -- true 2>/dev/null; then
            return 0
        fi
        sleep "$AGENT_WAIT_SLEEP"
        attempts=$((attempts + 1))
    done
    die "Incus agent in '$vm_name' did not become ready within $((AGENT_WAIT_ATTEMPTS * AGENT_WAIT_SLEEP))s."
}

# Shape a freshly-launched minimal Debian VM into the state a real user would
# have after a netinst install with the SSH-server tasksel ticked and one
# regular user created during install:
#   - openssh-server, sudo, python3 installed
#   - regular user with passwordless sudo and the user's SSH key authorized
#   - sshd enabled and running
shape_vm() {
    local vm_name="$1"
    local pubkey_file="$2"
    local pubkey
    pubkey="$(cat "$pubkey_file")"

    echo "  Shaping '$vm_name' (apt update, install ssh/sudo/python3, create '$BOOTSTRAP_USER')..."

    # apt is occasionally locked by background unattended-upgrades on first boot;
    # retry once after a short pause if needed.
    incus exec "$vm_name" -- bash -c '
        set -e
        for i in 1 2 3; do
            apt-get update -qq && break || sleep 5
        done
        DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
            openssh-server sudo python3 ca-certificates >/dev/null
        systemctl enable --now ssh
    '

    # Create user idempotently
    incus exec "$vm_name" -- bash -c "
        set -e
        id -u '$BOOTSTRAP_USER' >/dev/null 2>&1 || \
            useradd --create-home --shell /bin/bash '$BOOTSTRAP_USER'
        install -d -m 0755 -o '$BOOTSTRAP_USER' -g '$BOOTSTRAP_USER' \
            /home/'$BOOTSTRAP_USER'/.ssh
        echo '$pubkey' > /home/'$BOOTSTRAP_USER'/.ssh/authorized_keys
        chown '$BOOTSTRAP_USER:$BOOTSTRAP_USER' /home/'$BOOTSTRAP_USER'/.ssh/authorized_keys
        chmod 0600 /home/'$BOOTSTRAP_USER'/.ssh/authorized_keys
        echo '$BOOTSTRAP_USER ALL=(ALL) NOPASSWD:ALL' > /etc/sudoers.d/$BOOTSTRAP_USER
        chmod 0440 /etc/sudoers.d/$BOOTSTRAP_USER
    "
}

# Check whether a VM already exists
vm_exists() {
    incus info "$1" >/dev/null 2>&1
}

# Query a VM's IPv4 address from the default bridge
get_vm_ip() {
    local vm_name="$1"
    local ip=""
    local attempts=0

    while [[ -z "$ip" ]] && [[ $attempts -lt $IP_WAIT_ATTEMPTS ]]; do
        # Pick the first global-scope IPv4 from any interface that isn't loopback
        ip=$(incus list "$vm_name" --format json 2>/dev/null \
            | jq -r '
                .[0].state.network
                | to_entries[]
                | select(.key != "lo")
                | .value.addresses[]
                | select(.family == "inet" and .scope == "global")
                | .address
            ' \
            | head -n1)

        if [[ -z "$ip" ]]; then
            sleep "$IP_WAIT_SLEEP"
            attempts=$((attempts + 1))
        fi
    done

    if [[ -z "$ip" ]]; then
        die "Could not get IP for VM '$vm_name' after $((IP_WAIT_ATTEMPTS * IP_WAIT_SLEEP))s."
    fi

    echo "$ip"
}

# Wait until the VM's SSH port is reachable (cloud-init may still be running)
wait_for_ssh() {
    local ip="$1"
    local attempts=0
    while [[ $attempts -lt 60 ]]; do
        if (echo > /dev/tcp/"$ip"/22) 2>/dev/null; then
            return 0
        fi
        sleep 2
        attempts=$((attempts + 1))
    done
    die "SSH on $ip did not become reachable within 120s."
}

# --- Inventory generation ---

generate_inventory() {
    echo "Generating test inventory..."

    local vm_lines=""
    while IFS=: read -r vm_name vm_group; do
        local ip
        ip=$(get_vm_ip "$vm_name")
        wait_for_ssh "$ip"
        vm_lines="${vm_lines}${vm_name}:${vm_group}:${ip}"$'\n'
    done < <(read_vms)

    cat > "$INVENTORY_FILE" <<EOF
# Auto-generated by scripts/test-env.sh - do not edit manually.
all:
  children:
    servers:
      children:
EOF

    for group in $ALL_GROUPS; do
        local hosts=""
        while IFS=: read -r vm_name vm_group vm_ip; do
            if [[ "$vm_group" == "$group" ]]; then
                hosts="${hosts}            ${vm_name}:\n              ansible_host: ${vm_ip}\n              bootstrap_user: ${BOOTSTRAP_USER}\n"
            fi
        done <<< "$vm_lines"

        if [[ -n "$hosts" ]]; then
            echo "        ${group}:" >> "$INVENTORY_FILE"
            echo "          hosts:" >> "$INVENTORY_FILE"
            echo -e "$hosts" >> "$INVENTORY_FILE"
        else
            echo "        ${group}:" >> "$INVENTORY_FILE"
            echo "          hosts: {}" >> "$INVENTORY_FILE"
        fi
    done

    echo "Inventory written to $INVENTORY_FILE"
}

# --- Commands ---

cmd_create() {
    local pubkey_file="${SSH_PUBKEY_FILE:-$(detect_ssh_pubkey)}"
    echo "Using SSH public key: $pubkey_file"
    echo "Using image:          $INCUS_IMAGE"
    echo "Bootstrap user:       $BOOTSTRAP_USER"

    while IFS=: read -r vm_name vm_group; do
        if vm_exists "$vm_name"; then
            echo "VM '$vm_name' already exists, skipping launch."
        else
            echo "Creating VM '$vm_name' (group: $vm_group)..."
            incus launch "$INCUS_IMAGE" "$vm_name" \
                --vm \
                --config "limits.cpu=$VM_CPUS" \
                --config "limits.memory=$VM_MEMORY"
            wait_for_agent "$vm_name"
            shape_vm "$vm_name" "$pubkey_file"
        fi
    done < <(read_vms)

    generate_inventory
    echo ""
    echo "Done. Run 'make test-bootstrap' and 'make test-provision' to test your playbooks."
}

cmd_destroy() {
    while IFS=: read -r vm_name vm_group; do
        if vm_exists "$vm_name"; then
            echo "Destroying VM '$vm_name'..."
            incus delete --force "$vm_name"
        else
            echo "VM '$vm_name' not found, skipping."
        fi
    done < <(read_vms)

    rm -f "$INVENTORY_FILE"
    echo "Test inventory removed."
    echo "Done."
}

cmd_status() {
    echo "Defined VMs (from $VM_CONF):"
    echo ""
    printf "  %-20s %-20s %-15s %s\n" "NAME" "GROUP" "STATE" "IP"
    printf "  %-20s %-20s %-15s %s\n" "----" "-----" "-----" "--"

    while IFS=: read -r vm_name vm_group; do
        local state="not created"
        local ip="-"

        if vm_exists "$vm_name"; then
            state=$(incus list "$vm_name" --format json 2>/dev/null \
                | jq -r '.[0].status // "unknown"')
            ip=$(incus list "$vm_name" --format json 2>/dev/null \
                | jq -r '
                    .[0].state.network // {}
                    | to_entries[]?
                    | select(.key != "lo")
                    | .value.addresses[]?
                    | select(.family == "inet" and .scope == "global")
                    | .address
                ' \
                | head -n1)
            ip="${ip:--}"
        fi

        printf "  %-20s %-20s %-15s %s\n" "$vm_name" "$vm_group" "$state" "$ip"
    done < <(read_vms)
}

# --- Main ---

case "${1:-}" in
    create)  cmd_create  ;;
    destroy) cmd_destroy ;;
    status)  cmd_status  ;;
    *)
        echo "Usage: $0 {create|destroy|status}"
        exit 1
        ;;
esac
