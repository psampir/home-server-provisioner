#!/usr/bin/env bash
#
# Test environment management for home-server-provisioner.
#
# Thin wrapper around scripts/incus-env.sh that additionally seeds the
# test-specific configs/test/ tree (group_vars, vault password, stacks,
# dotfiles, Caddyfile). The test env is fully ephemeral - it is wiped
# and rebuilt from scratch on every `create` so test runs are reproducible.
#
# Usage:
#   ./scripts/test-env.sh create   - Launch VMs + seed configs/test/
#   ./scripts/test-env.sh destroy  - Delete VMs + remove configs/test/
#   ./scripts/test-env.sh status   - Show VM state

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

ENV_NAME="test"
ENV_DIR="$PROJECT_DIR/configs/$ENV_NAME"
EXAMPLE_DIR="$PROJECT_DIR/configs/example"
GROUP_VARS_DIR="$ENV_DIR/inventory/group_vars/all"
HOST_VARS_DIR="$ENV_DIR/inventory/host_vars"
VAULT_PASS_FILE="$ENV_DIR/.vault_pass"

# Persistent backing files for test VM data disks. Lives outside
# configs/test/ (which is wiped on every `destroy`) so the .img is
# reused across create/destroy cycles. Gitignored. The Incus device
# disappears with the VM at `destroy`; re-attaching at `create` is
# fast since the .img already exists.
TEST_DISKS_DIR="$PROJECT_DIR/.test-disks"
TEST_DATA_DISK_SIZE_MB=512
# Incus auto-derives the by-id path from the device name as
# "virtio-incus_<devname>". Keep the device name and the path in
# host_vars/hsp-app.yml in sync.
TEST_DATA_DISK_DEVNAME="data"
TEST_DATA_DISK_BYID="virtio-incus_${TEST_DATA_DISK_DEVNAME}"

# Static, throwaway vault password for the test env. It only protects
# auto-generated WireGuard keys for ephemeral VMs that are destroyed
# and recreated on every test cycle.
TEST_VAULT_PASSWORD="test-password"

# Throwaway credentials for the test Samba share served by hsp-vpn (see
# seed_test_nfs_server). Only ever used by ephemeral test VMs.
TEST_SMB_USER="smbtest"
TEST_SMB_PASS="smbpass123"

# VM shape for fixture VMs launched directly here (not via test-vms.conf).
# Same env-overridable defaults as incus-env.sh.
VM_CPUS="${VM_CPUS:-2}"
VM_MEMORY="${VM_MEMORY:-2GiB}"
INCUS_IMAGE="${INCUS_IMAGE:-images:debian/13}"

# --- Test lab LAN (dnsmasq DHCP/IPv6 fixture) -----------------------------
#
# Isolated, L2-only Incus network used to exercise the dnsmasq role's
# opt-in DHCPv4 + IPv6 RA server. It has NO Incus-managed L3 (ipv4.address
# and ipv6.address = none) so the segment has no DHCP/NAT of its own - the
# ONLY DHCP/RA authority is dnsmasq running on hsp-vpn.
#
# hsp-vpn (an inventory server) gets a 2nd NIC: the static LAN gateway +
# DHCP/RA server. hsp-client (a throwaway fixture VM, deliberately NOT in
# test-vms.conf so it never enters the Ansible inventory - the toolkit
# provisions servers, not clients) gets a 2nd NIC as a pure DHCP/SLAAC
# client. Both NICs use fixed MACs so the per-host systemd-networkd files
# can match deterministically.
TEST_LAB_NET="hsp-lab"
TEST_LAB_CLIENT="hsp-client"
# The 2nd NIC in an Incus VM is deterministically named enp6s0 (PCI slot 6;
# the primary NIC is enp5s0). dnsmasq binds DHCP by interface name, so this
# must be stable - verified empirically on this image.
TEST_LAB_IFACE="enp6s0"
TEST_LAB_SERVER_MAC="10:66:6a:00:50:01"
TEST_LAB_CLIENT_MAC="10:66:6a:00:50:02"
TEST_LAB_V4_GW="192.168.50.1"
TEST_LAB_V6_GW="fd50:abcd:1234::1"

# --- Test fixtures --------------------------------------------------------
#
# Each built-in role that takes user payload from configs/<env>/ should
# have at least one fixture here so the test-provision smoke run covers
# its happy path. Keep fixtures minimal: the goal is "did the role
# install/render/clean up something" - not full integration coverage.

# --- Test data disks ------------------------------------------------------
#
# Attach a small virtual disk to hsp-app so the storage role can be
# exercised against a real /dev/disk/by-id/ path. Backing file is
# persistent (in .test-disks/, gitignored) and reused across test
# create/destroy cycles. The Incus device disappears with the VM at
# destroy time; this function re-attaches it at every create.

seed_test_disks() {
    local vm_name="hsp-app"
    local disk_name="$TEST_DATA_DISK_DEVNAME"
    local img_file="$TEST_DISKS_DIR/${vm_name}-${disk_name}.img"

    mkdir -p "$TEST_DISKS_DIR"

    if [[ ! -f "$img_file" ]]; then
        echo "Creating test data disk image: $img_file (${TEST_DATA_DISK_SIZE_MB}M)..."
        truncate -s "${TEST_DATA_DISK_SIZE_MB}M" "$img_file"
    else
        echo "Reusing existing test data disk image: $img_file"
    fi

    # If the device is already attached (e.g. a previous create that
    # didn't go through destroy), drop it first so attach is idempotent.
    if incus config device show "$vm_name" 2>/dev/null | grep -qE "^${disk_name}:"; then
        echo "  Removing stale '$disk_name' device from $vm_name..."
        incus config device remove "$vm_name" "$disk_name" >/dev/null
    fi

    echo "  Attaching $img_file to $vm_name as device '$disk_name'..."
    incus config device add "$vm_name" "$disk_name" disk \
        source="$img_file" \
        io.bus=virtio-blk \
        > /dev/null

    # Wait for /dev/disk/by-id/<TEST_DATA_DISK_BYID> to appear inside the VM.
    # Incus derives this path automatically from the device name.
    local attempts=0
    while [[ $attempts -lt 15 ]]; do
        if incus exec "$vm_name" -- test -e "/dev/disk/by-id/${TEST_DATA_DISK_BYID}" 2>/dev/null; then
            echo "  Disk ready at /dev/disk/by-id/${TEST_DATA_DISK_BYID}"
            return 0
        fi
        sleep 1
        attempts=$((attempts + 1))
    done

    echo "  WARNING: /dev/disk/by-id/${TEST_DATA_DISK_BYID} not visible after 15s." >&2
    echo "  The storage role will fail. Inspect with: incus exec $vm_name -- ls -l /dev/disk/by-id/" >&2
    return 1
}

# --- Test NFS / Samba server ----------------------------------------------
#
# Stand up an NFS export and a Samba share on hsp-vpn so the
# network_mounts role can be exercised against real servers over the
# WireGuard tunnel. hsp-app mounts both (see host_vars/hsp-app.yml). The
# server listens on all interfaces but the NFS export is restricted to
# the WG subnet; mounts only succeed once WireGuard is up (i.e. after
# `make test-provision`). Firewall ports are opened by the firewall role
# via firewall_allow_rules (see seed_env_dir).
seed_test_nfs_server() {
    local vm_name="hsp-vpn"

    if ! incus info "$vm_name" >/dev/null 2>&1; then
        echo "  Skipping NFS/Samba test server: $vm_name not present."
        return 0
    fi

    echo "Setting up NFS + Samba test server on $vm_name ..."
    incus exec "$vm_name" -- env \
        SMB_USER="$TEST_SMB_USER" SMB_PASS="$TEST_SMB_PASS" \
        bash -euo pipefail <<'REMOTE'
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq nfs-kernel-server samba >/dev/null

mkdir -p /srv/test-nfs /srv/test-cifs
echo "hello-from-nfs"  > /srv/test-nfs/marker.txt
echo "hello-from-cifs" > /srv/test-cifs/marker.txt
chmod -R 0777 /srv/test-nfs /srv/test-cifs

# NFS export, restricted to the WireGuard subnet.
echo "/srv/test-nfs 10.10.0.0/24(rw,sync,no_subtree_check,no_root_squash)" > /etc/exports
exportfs -ra
systemctl enable --now nfs-kernel-server >/dev/null 2>&1

# Samba share (idempotent: only append the block once).
if ! grep -q '^\[testshare\]' /etc/samba/smb.conf; then
    cat >> /etc/samba/smb.conf <<EOF

[testshare]
   path = /srv/test-cifs
   browseable = yes
   read only = no
   guest ok = no
   valid users = ${SMB_USER}
EOF
fi
id "${SMB_USER}" >/dev/null 2>&1 || useradd -M -s /usr/sbin/nologin "${SMB_USER}"
printf '%s\n%s\n' "${SMB_PASS}" "${SMB_PASS}" | smbpasswd -s -a "${SMB_USER}" >/dev/null
smbpasswd -e "${SMB_USER}" >/dev/null
systemctl enable --now smbd >/dev/null 2>&1
systemctl restart smbd
REMOTE
    echo "  NFS export /srv/test-nfs and Samba //$vm_name/testshare ready."
}

# --- Test lab LAN (dnsmasq DHCP/IPv6) -------------------------------------
#
# Stand up an isolated L2 segment so the dnsmasq role's opt-in DHCPv4 +
# IPv6 RA server has something real to lease to. hsp-vpn becomes the DHCP/RA
# authority (static gateway on its 2nd NIC); hsp-client is a throwaway VM
# acting as a pure DHCP/SLAAC client on the same segment. dnsmasq itself is
# configured by the provision run (see host_vars/hsp-vpn.yml); this function
# only builds the network plumbing the role can't (and shouldn't) manage:
# the isolated network, the 2nd NICs, the static server address, and the
# client. Verification is done by `incus exec` against hsp-client.

# Block until the Incus agent answers in a freshly-launched VM.
wait_for_lab_agent() {
    local vm_name="$1" attempts=0
    while [[ $attempts -lt 60 ]]; do
        if incus exec "$vm_name" -- true 2>/dev/null; then
            return 0
        fi
        sleep 2
        attempts=$((attempts + 1))
    done
    echo "  WARNING: Incus agent in $vm_name not ready after 120s." >&2
    return 1
}

# Attach (idempotently) the lab NIC as device 'eth1' with a fixed MAC.
attach_lab_nic() {
    local vm_name="$1" mac="$2"
    if incus config device show "$vm_name" 2>/dev/null | grep -qE "^eth1:"; then
        incus config device remove "$vm_name" eth1 >/dev/null
    fi
    incus config device add "$vm_name" eth1 nic \
        network="$TEST_LAB_NET" name=eth1 hwaddr="$mac" >/dev/null
}

seed_test_lab_lan() {
    local server_vm="hsp-vpn"

    if ! incus info "$server_vm" >/dev/null 2>&1; then
        echo "  Skipping lab LAN: $server_vm not present."
        return 0
    fi

    echo "Setting up isolated lab LAN ($TEST_LAB_NET) for dnsmasq DHCP/IPv6 ..."

    # 1. Isolated L2-only network: no Incus DHCP/NAT/L3 (ipv4/ipv6 = none),
    #    so dnsmasq on hsp-vpn is the sole DHCP/RA authority on the segment.
    if ! incus network show "$TEST_LAB_NET" >/dev/null 2>&1; then
        incus network create "$TEST_LAB_NET" \
            ipv4.address=none ipv6.address=none >/dev/null
        echo "  Created network $TEST_LAB_NET (L2 only, no DHCP/NAT)."
    fi

    # 2. Throwaway client fixture VM (not in the inventory).
    if ! incus info "$TEST_LAB_CLIENT" >/dev/null 2>&1; then
        echo "  Launching client fixture VM $TEST_LAB_CLIENT ..."
        incus launch "$INCUS_IMAGE" "$TEST_LAB_CLIENT" --vm \
            --config "limits.cpu=$VM_CPUS" \
            --config "limits.memory=$VM_MEMORY" >/dev/null
        wait_for_lab_agent "$TEST_LAB_CLIENT"
    fi

    # 3. Attach the lab NIC to the server and the client (fixed MACs).
    attach_lab_nic "$server_vm"       "$TEST_LAB_SERVER_MAC"
    attach_lab_nic "$TEST_LAB_CLIENT" "$TEST_LAB_CLIENT_MAC"

    # 4. systemd-networkd config (matched by MAC, so interface naming is
    #    irrelevant). Server = static gateway and IS the router (no inbound
    #    RA). Client = DHCPv4 + accept RA/SLAAC. This mirrors the per-host
    #    "static server interface" step the README documents for production.
    incus exec "$server_vm" -- env \
        MAC="$TEST_LAB_SERVER_MAC" V4="$TEST_LAB_V4_GW" V6="$TEST_LAB_V6_GW" \
        bash -euo pipefail <<'REMOTE'
cat > /etc/systemd/network/10-lab.network <<EOF
[Match]
MACAddress=${MAC}

[Network]
Address=${V4}/24
Address=${V6}/64
# This host IS the router for the segment - do not autoconfigure from RAs.
IPv6AcceptRA=no
ConfigureWithoutCarrier=yes
EOF
networkctl reload 2>/dev/null || systemctl restart systemd-networkd
REMOTE

    incus exec "$TEST_LAB_CLIENT" -- env MAC="$TEST_LAB_CLIENT_MAC" \
        bash -euo pipefail <<'REMOTE'
cat > /etc/systemd/network/10-lab.network <<EOF
[Match]
MACAddress=${MAC}

[Network]
DHCP=ipv4
IPv6AcceptRA=yes
EOF
systemctl enable --now systemd-networkd >/dev/null 2>&1 || true
networkctl reload 2>/dev/null || systemctl restart systemd-networkd
REMOTE

    echo "  Lab LAN ready: $server_vm serves DHCP/RA on $TEST_LAB_IFACE ($TEST_LAB_V4_GW)."
    echo "  Verify after provision: incus exec $TEST_LAB_CLIENT -- ip -br addr show $TEST_LAB_IFACE"
}


seed_test_fixtures() {
    # custom_scripts: one common script for every host, plus one
    # host-specific script that should land only on hsp-app.
    mkdir -p "$ENV_DIR/scripts/_common" "$ENV_DIR/scripts/hsp-app"

    cat > "$ENV_DIR/scripts/_common/hsp-test-common.sh" <<'FIXTURE_EOF'
#!/usr/bin/env bash
echo "common script on $(hostname)"
FIXTURE_EOF
    chmod 0755 "$ENV_DIR/scripts/_common/hsp-test-common.sh"

    cat > "$ENV_DIR/scripts/hsp-app/hsp-test-app-only.sh" <<'FIXTURE_EOF'
#!/usr/bin/env bash
echo "host-only script on $(hostname)"
FIXTURE_EOF
    chmod 0755 "$ENV_DIR/scripts/hsp-app/hsp-test-app-only.sh"

    # systemd_units: a one-shot oneshot service that calls the common
    # custom_scripts fixture. Exercises both the common-overlay copy
    # path and the auto-enable logic; running 'systemctl start
    # hsp-test-unit.service' on a host should print the script's
    # output to the journal.
    mkdir -p "$ENV_DIR/systemd/_common"
    cat > "$ENV_DIR/systemd/_common/hsp-test-unit.service" <<'FIXTURE_EOF'
[Unit]
Description=home-server-provisioner test unit (oneshot)
After=network-online.target
OnFailure=hsp-notify-failure@%n.service

[Service]
Type=oneshot
ExecStart=/usr/local/bin/hsp-test-common.sh
RemainAfterExit=no

[Install]
WantedBy=multi-user.target
FIXTURE_EOF
}

# --- Config tree seeding ---------------------------------------------------

seed_env_dir() {
    echo "Seeding configs/$ENV_NAME/ ..."

    mkdir -p "$GROUP_VARS_DIR"

    printf "%s" "$TEST_VAULT_PASSWORD" > "$VAULT_PASS_FILE"
    chmod 600 "$VAULT_PASS_FILE"

    cat > "$GROUP_VARS_DIR/main.yml" <<'EOF'
# Auto-generated by scripts/test-env.sh - do not edit manually.

# SSH public key for the service user (matches the key authorized on the VMs).
service_user_ssh_pubkey: "{{ lookup('file', lookup('env', 'SSH_PUBKEY_FILE') | default('~/.ssh/id_ed25519.pub', true)) }}"

# --- admin_user role ---
admin_user_name: testadmin
admin_user_shell: fish
admin_user_extra_packages:
  - fish
  - zoxide
  - fastfetch

# --- firewall role --- open whoami port for smoke testing
firewall_allow_rules:
  - { port: 8080, proto: tcp, comment: "whoami (test stack, direct)" }
  # network_mounts role test: hsp-vpn serves an NFS export and a Samba
  # share to hsp-app over the WG subnet (see seed_test_nfs_server()).
  - { port: 111, proto: tcp, from: "10.10.0.0/24", comment: "test NFS rpcbind" }
  - { port: 2049, proto: tcp, from: "10.10.0.0/24", comment: "test NFS" }
  - { port: 445, proto: tcp, from: "10.10.0.0/24", comment: "test SMB" }
  - { port: 139, proto: tcp, from: "10.10.0.0/24", comment: "test SMB (netbios)" }

# --- dnsmasq role --- map whoami.home → hub IP so 'curl https://whoami.home/'
# from any WG peer transparently hits Caddy on the hub.
dnsmasq_extra_hosts:
  - { name: whoami, ip: 10.10.0.1 }

# --- compose_deploy role ---
# Stacks are auto-discovered from configs/test/stacks/_common/ and
# configs/test/stacks/<hostname>/ - no explicit list needed here.

# --- wireguard role ---
# Declare a single test client; keys are generated into vault.yml by
# scripts/wg-ensure-keys.py (invoked automatically by 'make provision').
wireguard_clients:
  - name: test-controller
    vpn_ip: 10.10.0.20

wireguard_client_keys: "{{ vault_wireguard_client_keys | default({}) }}"

# --- borgmatic / borg_repo roles ---
# Throwaway repo passphrase for the ephemeral test env. In prod this comes
# from ansible-vault (vault_borgmatic_passphrase). The test topology proves
# both multi-source and multi-target: hsp-app -> {hsp-backup, hsp-backup2}
# and hsp-app2 -> hsp-backup. See host_vars/hsp-app.yml and host_vars/hsp-app2.yml.
borgmatic_passphrase: "test-borg-passphrase"
EOF

    # Stacks + dotfiles come straight from configs/example/ so a test
    # provision exercises the exact same code paths as a prod provision.
    rm -rf "$ENV_DIR/stacks" "$ENV_DIR/dotfiles" "$ENV_DIR/caddy" "$ENV_DIR/scripts" "$ENV_DIR/systemd"
    cp -a "$EXAMPLE_DIR/stacks" "$ENV_DIR/stacks"
    cp -a "$EXAMPLE_DIR/dotfiles" "$ENV_DIR/dotfiles"

    # Fixtures for built-in user-payload roles (custom_scripts, etc.).
    # Each one exercises a code path the role advertises, so a successful
    # `make test-provision` proves the role works end-to-end.
    seed_test_fixtures

    # Per-host overrides. hsp-app gets a storage_volumes entry that
    # references the virtual data disk attached by seed_test_disks().
    # The /dev/disk/by-id/ path is deterministic because we set a fixed
    # serial on the Incus disk device (see TEST_DATA_DISK_SERIAL).
    mkdir -p "$HOST_VARS_DIR"
    cat > "$HOST_VARS_DIR/hsp-app.yml" <<EOF
# Auto-generated by scripts/test-env.sh - do not edit manually.

# --- storage role ---
# Backed by .test-disks/hsp-app-data.img, attached to the VM as device
# 'data' with a fixed serial so the by-id path is stable across reboots.
storage_volumes:
  - device: /dev/disk/by-id/$TEST_DATA_DISK_BYID
    mount: /mnt/test-data
    fstype: ext4
    mount_opts: "defaults,nofail,noatime"

# --- network_mounts role ---
# NFS export + Samba share served from hsp-vpn (10.10.0.1) over the
# WireGuard tunnel, set up by seed_test_nfs_server(). CIFS credentials
# are throwaway test values for the ephemeral VM; in prod they come
# from ansible-vault.
network_mounts_shares:
  - type: nfs
    source: "10.10.0.1:/srv/test-nfs"
    mount: /mnt/test-nfs
    mount_opts: "vers=4.2"
  - type: cifs
    source: "//10.10.0.1/testshare"
    mount: /mnt/test-cifs
    mount_opts: "uid=root,gid=root"
    credentials_username: $TEST_SMB_USER
    credentials_password: $TEST_SMB_PASS

# --- borgmatic role ---
# hsp-app exercises MULTIPLE TARGETS: it pushes /etc to two independent
# borg repos - hsp-backup (10.10.0.3) and hsp-backup2 (10.10.0.5) - over
# the WireGuard tunnel. Each target runs the borg_repo role and authorizes
# this host's key append-only (restricted to /srv/borg/hsp-app). Labels
# must be distinct because both repos share the path 'main'.
borgmatic_source_directories:
  - /etc
borgmatic_repositories:
  - target: hsp-backup
    path: main
    label: primary
  - target: hsp-backup2
    path: main
    label: offsite
EOF

    # hsp-app2 is a SECOND source. Together with hsp-app it proves the
    # MULTIPLE SOURCES case on hsp-backup: borg_repo there discovers both
    # hosts and gives each its own /srv/borg/<host>/ subtree + key line.
    cat > "$HOST_VARS_DIR/hsp-app2.yml" <<'EOF'
# Auto-generated by scripts/test-env.sh - do not edit manually.

# --- borgmatic role ---
# hsp-app2 pushes /etc to hsp-backup only. This makes hsp-backup a repo
# server for two sources (hsp-app + hsp-app2), exercising per-source
# isolation (separate repo dirs + append-only authorized_keys lines).
borgmatic_source_directories:
  - /etc
borgmatic_repositories:
  - target: hsp-backup
    path: main
    label: primary
EOF

    # hsp-vpn is the DHCP/RA authority for the isolated lab LAN (see
    # seed_test_lab_lan()). It already runs dnsmasq as a DNS server for the
    # WireGuard subnet; here we opt it into the DHCPv4 + IPv6 SLAAC server on
    # its 2nd NIC ($TEST_LAB_IFACE, static $TEST_LAB_V4_GW) facing hsp-client.
    # This exercises course requirement #1 (server static / client dynamic,
    # IPv4 + IPv6). dnsmasq_dhcp_v4_dns is a plain string (dnsmasq option 6).
    cat > "$HOST_VARS_DIR/hsp-vpn.yml" <<EOF
# Auto-generated by scripts/test-env.sh - do not edit manually.

# --- dnsmasq role: opt-in DHCPv4 + IPv6 RA (SLAAC) server ---
# Exercised on the isolated, L2-only 'hsp-lab' Incus network. hsp-vpn holds
# a static address ($TEST_LAB_V4_GW / $TEST_LAB_V6_GW) on its 2nd NIC
# ($TEST_LAB_IFACE); hsp-client (a throwaway fixture VM, NOT in the
# inventory) is a pure DHCP/SLAAC client on the same segment. dnsmasq is the
# sole DHCP/RA authority there.
dnsmasq_dhcp_enabled: true
dnsmasq_dhcp_interface: $TEST_LAB_IFACE
dnsmasq_dhcp_v4:
  start: 192.168.50.50
  end: 192.168.50.200
  netmask: 255.255.255.0
  lease: 1h
dnsmasq_dhcp_v4_gateway: $TEST_LAB_V4_GW
dnsmasq_dhcp_v4_dns: "$TEST_LAB_V4_GW"
dnsmasq_dhcp_v6_mode: slaac
dnsmasq_dhcp_v6_prefix: fd50:abcd:1234::/64
dnsmasq_dhcp_open_firewall: true
EOF

    # (everything commented out) - write a real test-specific one that
    # reverse-proxies whoami over the WireGuard tunnel using Caddy's
    # internal CA.
    mkdir -p "$ENV_DIR/caddy"
    cat > "$ENV_DIR/caddy/Caddyfile" <<'CADDY_EOF'
# Auto-generated by scripts/test-env.sh - do not edit manually.
#
# Caddy runs on hsp-vpn (10.10.0.1) and reverse-proxies whoami on
# hsp-app (10.10.0.2:8080) over the WireGuard tunnel. `tls internal`
# uses Caddy's local CA - clients hit it with `curl -k`.

{
    # No public ACME - every site below uses `tls internal`.
}

whoami.home {
    tls internal
    reverse_proxy 10.10.0.2:8080
}
CADDY_EOF
}

# --- Commands -------------------------------------------------------------

cmd_create() {
    # Seed configs/ FIRST so incus-env.sh has a place to write the inventory.
    seed_env_dir
    "$SCRIPT_DIR/incus-env.sh" "$ENV_NAME" create
    seed_test_disks
    seed_test_nfs_server
    seed_test_lab_lan
}

cmd_destroy() {
    "$SCRIPT_DIR/incus-env.sh" "$ENV_NAME" destroy

    # Lab LAN fixtures. hsp-vpn's 2nd NIC vanished with the VM above; tear
    # down the client fixture and the isolated network (the network can only
    # be removed once nothing is attached to it).
    if incus info "$TEST_LAB_CLIENT" >/dev/null 2>&1; then
        incus delete --force "$TEST_LAB_CLIENT" >/dev/null \
            && echo "Deleted client fixture VM $TEST_LAB_CLIENT."
    fi
    if incus network show "$TEST_LAB_NET" >/dev/null 2>&1; then
        incus network delete "$TEST_LAB_NET" >/dev/null \
            && echo "Deleted lab network $TEST_LAB_NET."
    fi

    if [[ -d "$ENV_DIR" ]]; then
        rm -rf "$ENV_DIR"
        echo "Removed $ENV_DIR."
    fi
}

cmd_status() {
    "$SCRIPT_DIR/incus-env.sh" "$ENV_NAME" status
}

case "${1:-}" in
    create)  cmd_create  ;;
    destroy) cmd_destroy ;;
    status)  cmd_status  ;;
    *)
        echo "Usage: $0 {create|destroy|status}" >&2
        exit 1
        ;;
esac
