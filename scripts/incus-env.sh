#!/usr/bin/env bash
#
# Generic Incus VM manager for any home-server-provisioner environment.
#
# Reads VM definitions from scripts/<env>-vms.conf and manages Incus VMs
# plus the auto-generated configs/<env>/inventory/hosts.yml that pins each
# VM's name to its current IP.
#
# This script handles ONLY the Incus + inventory side. It does NOT touch
# group_vars/, stacks/, dotfiles/, caddy/, or .vault_pass - those are the
# caller's responsibility (e.g. test-env.sh seeds them; for a long-lived
# env you maintain them yourself in configs/<env>/'s own git repo).
#
# Usage:
#   ./scripts/incus-env.sh <env> create   - Launch VMs + write hosts.yml
#   ./scripts/incus-env.sh <env> destroy  - Delete VMs (configs/<env>/ stays)
#   ./scripts/incus-env.sh <env> status   - Show VM state
#
# Prerequisites:
#   - incus installed + initialised
#   - user in 'incus-admin' group
#   - jq
#   - configs/<env>/ already exists (e.g. via 'make init-config ENV=<env>')
#
# vms.conf format (one VM per line, # comments allowed):
#   VM_NAME:GROUP[,GROUP...][:KEY=VAL,KEY=VAL...]
#
# Groups must match inventory groups (app_servers, backup_targets,
# vpn_server). Optional 3rd field: comma-separated KEY=VAL pairs inlined
# under the host (vpn_ip, wireguard_role, …). Values are verbatim YAML.
#
# Note on coexisting environments: Incus VM names are global, so when
# running two envs side-by-side give them distinct names in each vms.conf
# (e.g. hsp-app vs demo-hsp-app).

set -euo pipefail

# --- Argument parsing ---

if [[ $# -lt 2 ]]; then
    echo "Usage: $0 <env> {create|destroy|status}" >&2
    exit 1
fi

ENV_NAME="$1"
ACTION="$2"

# --- Configuration ---

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

VM_CONF="$SCRIPT_DIR/${ENV_NAME}-vms.conf"
ENV_DIR="$PROJECT_DIR/configs/$ENV_NAME"
INVENTORY_DIR="$ENV_DIR/inventory"
INVENTORY_FILE="$INVENTORY_DIR/hosts.yml"

VM_CPUS="${VM_CPUS:-2}"
VM_MEMORY="${VM_MEMORY:-2GiB}"
INCUS_IMAGE="${INCUS_IMAGE:-images:debian/13}"
BOOTSTRAP_USER="${BOOTSTRAP_USER:-testadmin}"

ALL_GROUPS="app_servers backup_targets vpn_server"

IP_WAIT_ATTEMPTS=30
IP_WAIT_SLEEP=2
AGENT_WAIT_ATTEMPTS=30
AGENT_WAIT_SLEEP=2

# --- Helpers ---

die() { echo "Error: $1" >&2; exit 1; }

require_cmd() {
    command -v "$1" >/dev/null 2>&1 || die "'$1' is required but not installed."
}

require_cmd incus
require_cmd jq

[[ -f "$VM_CONF" ]] || die "VM definitions not found: $VM_CONF"

read_vms() {
    grep -v '^\s*#' "$VM_CONF" | grep -v '^\s*$'
}

detect_ssh_pubkey() {
    local key=""
    for candidate in "$HOME/.ssh/id_ed25519.pub" "$HOME/.ssh/id_rsa.pub" "$HOME/.ssh/id_ecdsa.pub"; do
        if [[ -f "$candidate" ]]; then
            key="$candidate"
            break
        fi
    done
    [[ -n "$key" ]] || die "No SSH public key found. Set SSH_PUBKEY_FILE in .env or create one with ssh-keygen."
    echo "$key"
}

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

# Shape a freshly-launched minimal Debian VM into the state a real user
# would have after a netinst install with sshd + one sudo user.
shape_vm() {
    local vm_name="$1"
    local pubkey_file="$2"
    local pubkey
    pubkey="$(cat "$pubkey_file")"

    echo "  Shaping '$vm_name' (apt, ssh, sudo, user '$BOOTSTRAP_USER')..."

    incus exec "$vm_name" -- bash -c '
        set -e
        for i in 1 2 3; do
            apt-get update -qq && break || sleep 5
        done
        DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
            openssh-server sudo python3 ca-certificates >/dev/null
        systemctl enable --now ssh
    '

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

vm_exists() {
    incus info "$1" >/dev/null 2>&1
}

get_vm_ip() {
    local vm_name="$1"
    local ip=""
    local attempts=0

    while [[ -z "$ip" ]] && [[ $attempts -lt $IP_WAIT_ATTEMPTS ]]; do
        ip=$(incus list "$vm_name" --format json 2>/dev/null \
            | jq -r '
                .[0].state.network
                | to_entries[]
                | select(.key | test("^(lo|docker|br-|veth|cni-|wg|tun|tap|virbr)") | not)
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

    [[ -n "$ip" ]] || die "Could not get IP for VM '$vm_name' after $((IP_WAIT_ATTEMPTS * IP_WAIT_SLEEP))s."
    echo "$ip"
}

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
    echo "Generating inventory at $INVENTORY_FILE ..."

    mkdir -p "$INVENTORY_DIR"

    local vm_lines=""
    while IFS=: read -r -u 3 vm_name vm_groups vm_extra; do
        local ip
        ip=$(get_vm_ip "$vm_name")
        wait_for_ssh "$ip"
        vm_lines="${vm_lines}${vm_name}	${vm_groups}	${ip}	${vm_extra:-}"$'\n'
    done 3< <(read_vms)

    cat > "$INVENTORY_FILE" <<EOF
# Auto-generated by scripts/incus-env.sh - do not edit manually.
# Regenerate by running: ./scripts/incus-env.sh $ENV_NAME create
all:
  children:
    servers:
      children:
EOF

    for group in $ALL_GROUPS; do
        local hosts=""
        while IFS=$'\t' read -r vm_name vm_groups vm_ip vm_extra; do
            [[ -z "$vm_name" ]] && continue
            if [[ ",${vm_groups}," == *",${group},"* ]]; then
                hosts="${hosts}            ${vm_name}:\n              ansible_host: ${vm_ip}\n              bootstrap_user: ${BOOTSTRAP_USER}\n"
                if [[ -n "$vm_extra" ]]; then
                    local IFS_save="$IFS"
                    IFS=','
                    for kv in $vm_extra; do
                        local k="${kv%%=*}"
                        local v="${kv#*=}"
                        hosts="${hosts}              ${k}: ${v}\n"
                    done
                    IFS="$IFS_save"
                fi
            fi
        done <<< "$vm_lines"

        if [[ -n "$hosts" ]]; then
            echo "        ${group}:" >> "$INVENTORY_FILE"
            echo "          hosts:" >> "$INVENTORY_FILE"
            printf "%b" "$hosts" >> "$INVENTORY_FILE"
        else
            echo "        ${group}:" >> "$INVENTORY_FILE"
            echo "          hosts: {}" >> "$INVENTORY_FILE"
        fi
    done

    echo "Inventory written."
}

# --- Commands ---

cmd_create() {
    local pubkey_file="${SSH_PUBKEY_FILE:-$(detect_ssh_pubkey)}"
    echo "Environment:      $ENV_NAME"
    echo "VM definitions:   $VM_CONF"
    echo "SSH public key:   $pubkey_file"
    echo "Incus image:      $INCUS_IMAGE"
    echo "Bootstrap user:   $BOOTSTRAP_USER"
    echo ""

    while IFS=: read -r -u 3 vm_name vm_groups _vm_extra; do
        if vm_exists "$vm_name"; then
            echo "VM '$vm_name' already exists, skipping launch."
        else
            echo "Creating VM '$vm_name' (groups: $vm_groups)..."
            incus launch "$INCUS_IMAGE" "$vm_name" \
                --vm \
                --config "limits.cpu=$VM_CPUS" \
                --config "limits.memory=$VM_MEMORY" \
                < /dev/null
            wait_for_agent "$vm_name"
            shape_vm "$vm_name" "$pubkey_file"
        fi
    done 3< <(read_vms)

    generate_inventory
    echo ""
    echo "Done. configs/$ENV_NAME/ is ready for: make bootstrap ENV=$ENV_NAME"
}

cmd_destroy() {
    while IFS=: read -r -u 3 vm_name vm_groups _vm_extra; do
        if vm_exists "$vm_name"; then
            echo "Destroying VM '$vm_name'..."
            incus delete --force "$vm_name"
        else
            echo "VM '$vm_name' not found, skipping."
        fi
    done 3< <(read_vms)

    echo "Done. configs/$ENV_NAME/ left intact (caller's responsibility)."
}

cmd_status() {
    echo "Environment: $ENV_NAME"
    echo "Defined VMs (from $VM_CONF):"
    echo ""
    printf "  %-30s %-25s %-15s %s\n" "NAME" "GROUPS" "STATE" "IP"
    printf "  %-30s %-25s %-15s %s\n" "----" "------" "-----" "--"

    while IFS=: read -r -u 3 vm_name vm_groups _vm_extra; do
        local state="not created"
        local ip="-"

        if vm_exists "$vm_name"; then
            state=$(incus list "$vm_name" --format json 2>/dev/null \
                | jq -r '.[0].status // "unknown"')
            ip=$(incus list "$vm_name" --format json 2>/dev/null \
                | jq -r '
                    .[0].state.network // {}
                    | to_entries[]?
                    | select(.key | test("^(lo|docker|br-|veth|cni-|wg|tun|tap|virbr)") | not)
                    | .value.addresses[]?
                    | select(.family == "inet" and .scope == "global")
                    | .address
                ' \
                | head -n1)
            ip="${ip:--}"
        fi

        printf "  %-30s %-25s %-15s %s\n" "$vm_name" "$vm_groups" "$state" "$ip"
    done 3< <(read_vms)
}

case "$ACTION" in
    create)  cmd_create  ;;
    destroy) cmd_destroy ;;
    status)  cmd_status  ;;
    *)
        echo "Usage: $0 <env> {create|destroy|status}" >&2
        exit 1
        ;;
esac
