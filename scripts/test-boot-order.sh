#!/usr/bin/env bash
#
# Boot-order test on the Incus test lab.
#
# Verifies the failure mode found on the production hosts: Docker starts
# before a late data mount, containers bind the empty root-fs directory, and
# hsp-boot-check must report it. Then removes the Docker ordering drop-in to
# prove the check actually fails, restores it, and verifies a clean boot.
#
# Requires a provisioned test environment:
#   make test-env-create
#   make test-provision
#
# The test reboots hsp-app twice and restores its configuration at the end.
# Exit code is the number of failed checks (0 = all green).

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

VM="${TEST_BOOT_VM:-hsp-app}"
MOUNT="${TEST_BOOT_MOUNT:-/srv/data}"
BOOT_CHECK="${TEST_BOOT_CHECK:-/usr/local/bin/hsp-boot-check}"
FIXTURE_CONTAINER="hsp-boot-fixture"

FAILS=0
VM_RESTORED=0

if [[ -t 1 ]]; then
    GREEN='\033[0;32m'; RED='\033[0;31m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; RESET='\033[0m'
else
    GREEN=''; RED=''; YELLOW=''; BLUE=''; RESET=''
fi

host() { printf '\n%s=== %s ===%s\n' "$BLUE" "$*" "$RESET"; }
step() { printf '%s--> %s%s\n' "$YELLOW" "$*" "$RESET"; }
ok()   { printf '  %sOK %s%s\n' "$GREEN" "$*" "$RESET"; }
fail() { printf '  %sFAIL %s%s\n' "$RED" "$*" "$RESET"; FAILS=$((FAILS + 1)); }

vm() {
    incus exec "$VM" -- env SYSTEMD_PAGER= "$@"
}

wait_agent() {
    local attempts=0
    while (( attempts < 90 )); do
        incus exec "$VM" -- true >/dev/null 2>&1 && return 0
        sleep 2
        attempts=$((attempts + 1))
    done
    return 1
}

wait_system() {
    local attempts=0 state=""
    while (( attempts < 90 )); do
        state="$(vm systemctl is-system-running 2>/dev/null || true)"
        [[ "$state" == "running" || "$state" == "degraded" ]] && return 0
        sleep 2
        attempts=$((attempts + 1))
    done
    return 1
}

reboot_vm() {
    incus restart "$VM" >/dev/null 2>&1 || return 1
    wait_agent || return 1
    wait_system || return 1
}

restore_config() {
    incus exec "$VM" -- bash -s >/dev/null 2>&1 <<'REMOTE' || true
set -e
mkdir -p /etc/systemd/system/docker.service.d
cat >/etc/systemd/system/docker.service.d/10-hsp-mounts.conf <<'UNIT'
# Managed by Ansible - do not edit manually.
[Unit]
RequiresMountsFor=/srv/data
UNIT
rm -f /etc/systemd/system/srv-data.mount.d/10-delay.conf
rmdir /etc/systemd/system/srv-data.mount.d 2>/dev/null || true
rm -f /etc/systemd/system/slow-data.service
systemctl daemon-reload
REMOTE
    incus exec "$VM" -- docker rm -f "$FIXTURE_CONTAINER" >/dev/null 2>&1 || true
    VM_RESTORED=1
}

cleanup() {
    local rc=$?
    trap - EXIT
    if (( FAILS > 0 )) && (( VM_RESTORED == 0 )) && incus info "$VM" >/dev/null 2>&1; then
        step "Restoring the VM after a failed test"
        restore_config
    fi
    exit "$rc"
}
trap cleanup EXIT

# --- Pre-flight -----------------------------------------------------------

host "Pre-flight: $VM"

if ! incus info "$VM" >/dev/null 2>&1; then
    fail "$VM does not exist; run 'make test-env-create' and 'make test-provision'"
    exit "$FAILS"
fi

if ! vm test -x "$BOOT_CHECK"; then
    fail "$BOOT_CHECK is missing; run 'make test-provision' (boot_check must be enabled)"
    exit "$FAILS"
fi

if ! vm systemctl is-active --quiet docker; then
    fail "docker is not active on $VM"
    exit "$FAILS"
fi

if ! vm findmnt -rn -M "$MOUNT" >/dev/null 2>&1; then
    fail "$MOUNT is not mounted on $VM; run 'make test-provision'"
    exit "$FAILS"
fi

if ! vm systemctl show docker.service -p RequiresMountsFor --value | grep -qw -- "$MOUNT"; then
    fail "docker.service does not have RequiresMountsFor=$MOUNT; run 'make test-provision'"
    exit "$FAILS"
fi

ok "$MOUNT mounted and docker.service ordered after it"

# --- Fixture container ----------------------------------------------------

step "Starting the bind-mount fixture container"
if ! vm docker inspect "$FIXTURE_CONTAINER" >/dev/null 2>&1; then
    if ! vm docker run -d --name "$FIXTURE_CONTAINER" --restart unless-stopped \
        -v "$MOUNT:/data" busybox sleep 100000 >/dev/null; then
        fail "could not start $FIXTURE_CONTAINER (busybox pull failed?)"
        exit "$FAILS"
    fi
fi
vm docker start "$FIXTURE_CONTAINER" >/dev/null 2>&1 || true
if [[ "$(vm docker inspect -f '{{.State.Running}}' "$FIXTURE_CONTAINER" 2>/dev/null || true)" != "true" ]]; then
    fail "$FIXTURE_CONTAINER is not running"
    exit "$FAILS"
fi
ok "$FIXTURE_CONTAINER runs with $MOUNT bind-mounted"

# --- Positive: delayed mount, Docker must wait ----------------------------

step "Adding a 60 s delay to srv-data.mount"
if ! incus exec "$VM" -- bash -s <<'REMOTE'
set -e
cat >/etc/systemd/system/slow-data.service <<'UNIT'
[Unit]
Description=Delay /srv/data for the boot-order test
[Service]
Type=oneshot
ExecStart=/bin/sleep 60
UNIT
mkdir -p /etc/systemd/system/srv-data.mount.d
cat >/etc/systemd/system/srv-data.mount.d/10-delay.conf <<'UNIT'
[Unit]
Wants=slow-data.service
After=slow-data.service
UNIT
systemctl daemon-reload
systemctl cat srv-data.mount | grep -q slow-data.service
REMOTE
then
    fail "could not install the delayed-mount drop-in"
    exit "$FAILS"
fi

step "Rebooting $VM (positive case)"
if ! reboot_vm; then
    fail "$VM did not come back after reboot"
    exit "$FAILS"
fi

if out="$(vm "$BOOT_CHECK" 2>&1)"; then
    ok "boot check passed with the delayed mount"
else
    fail "boot check failed with the delayed mount"
    printf '%s\n' "$out"
fi

# --- Negative: remove Docker ordering -------------------------------------

step "Negative: removing the Docker mount-ordering drop-in"
vm bash -c 'rm -f /etc/systemd/system/docker.service.d/10-hsp-mounts.conf; systemctl daemon-reload' || true

step "Rebooting $VM (negative case)"
if ! reboot_vm; then
    fail "$VM did not come back after the negative reboot"
    exit "$FAILS"
fi

if out="$(vm "$BOOT_CHECK" 2>&1)"; then
    fail "boot check passed without Docker mount ordering - expected failure"
else
    ok "boot check failed as expected without RequiresMountsFor"
    if grep -qE 'RequiresMountsFor|stale bind' <<< "$out"; then
        ok "failure names the missing ordering or the stale bind"
    else
        fail "failure did not mention RequiresMountsFor or a stale bind"
        printf '%s\n' "$out"
    fi
fi

# --- Restore and verify ---------------------------------------------------

step "Restoring the Docker drop-in and removing the delay"
restore_config

step "Rebooting $VM (restored case)"
if ! reboot_vm; then
    fail "$VM did not come back after the restore reboot"
    exit "$FAILS"
fi

if out="$(vm "$BOOT_CHECK" 2>&1)"; then
    ok "boot check passed after restoring the drop-in"
else
    fail "boot check failed after restoring the drop-in"
    printf '%s\n' "$out"
fi

printf "\n"
if (( FAILS == 0 )); then
    printf "${GREEN}All boot-order checks passed.${RESET}\n"
else
    printf "${RED}%d boot-order check(s) failed.${RESET}\n" "$FAILS"
fi
exit "$FAILS"
