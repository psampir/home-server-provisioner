#!/usr/bin/env bash
#
# Reboot persistence check for the test environment.
#
# Reboots every test VM and verifies that the infrastructure services this
# project configures come back up automatically - i.e. they are `enabled`
# (start on boot) AND `active` afterwards, the firewall is still up, and
# every timer that was active before the reboot is active again.
#
# This validates the Milestone 3 item "service startup and persistence
# across reboots": provisioning is not enough - the services must survive a
# power cycle without manual intervention.
#
# Method, per VM:
#   1. Snapshot the active timers (the "before" set).
#   2. `incus restart` the VM and wait for the agent + system to settle.
#   3. Assert the per-group headline services are enabled + active.
#   4. Assert `ufw` reports Status: active.
#   5. Assert every timer that was active before is active again.
#
# Headline services are curated from the role->group mapping in
# playbooks/site.yml (ssh/fail2ban/wireguard everywhere; dnsmasq+caddy on
# the VPN hub; docker on app servers). Services that legitimately do not run
# on virtual hardware (e.g. smartd on virtual disks) are intentionally not
# asserted. Timers are checked generically (before subset of after) so the
# check does not hardcode fixture-specific timer names.
#
# Requires:
#   - a successful `make test-provision` run (VMs in steady state)
#   - the Incus VMs from scripts/test-vms.conf to be running
#
# Usage:
#   ./scripts/test-reboot-check.sh
#   make test-reboot
#
# Exit code is the count of failed checks (0 = all green).

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VM_CONF="$SCRIPT_DIR/test-vms.conf"

# How long to wait for a VM to become usable again after `incus restart`.
AGENT_WAIT_ATTEMPTS=60
AGENT_WAIT_SLEEP=2
SETTLE_WAIT_ATTEMPTS=30
SETTLE_WAIT_SLEEP=2

FAILS=0

# --- Colour helpers (match scripts/test-smoke.sh) ---
if [[ -t 1 ]]; then
    GREEN='\033[0;32m'; RED='\033[0;31m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; RESET='\033[0m'
else
    GREEN=''; RED=''; YELLOW=''; BLUE=''; RESET=''
fi

host()  { printf '\n%s=== %s ===%s\n' "$BLUE" "$*" "$RESET"; }
step()  { printf '%s--> %s%s\n' "$YELLOW" "$*" "$RESET"; }
ok()    { printf '  %sOK %s%s\n' "$GREEN" "$*" "$RESET"; }
fail()  { printf '  %sFAIL %s%s\n' "$RED" "$*" "$RESET"; FAILS=$((FAILS + 1)); }
warn()  { printf '  %sWARN %s%s\n' "$YELLOW" "$*" "$RESET"; }

# Run a command inside a VM with the systemd pager disabled (incus exec
# allocates a TTY, which would otherwise trigger a pager on systemctl).
vm() {
    local vm_name="$1"; shift
    incus exec "$vm_name" -- env SYSTEMD_PAGER= "$@"
}

# Headline services that MUST be enabled + active after reboot, given a VM's
# group membership. Every VM is implicitly in the baseline "servers" group.
expected_services_for() {
    local groups="$1"
    # Baseline (all servers).
    echo "ssh fail2ban wg-quick@wg0"
    case ",${groups}," in
        *,vpn_server,*)    echo "dnsmasq caddy" ;;
    esac
    case ",${groups}," in
        *,app_servers,*)   echo "docker" ;;
    esac
}

assert_service() {
    local vm_name="$1" unit="$2"
    local en ac
    en="$(vm "$vm_name" systemctl is-enabled "$unit" 2>/dev/null || true)"
    ac="$(vm "$vm_name" systemctl is-active  "$unit" 2>/dev/null || true)"
    if [[ "$en" == "enabled" && "$ac" == "active" ]]; then
        ok "$unit (enabled, active)"
    else
        fail "$unit (is-enabled=$en, is-active=$ac) - expected enabled+active"
    fi
}

active_timers() {
    local vm_name="$1"
    vm "$vm_name" systemctl list-units --type=timer --state=active \
        --no-legend --plain 2>/dev/null | awk '{print $1}' | sort
}

check_vm() {
    local vm_name="$1" groups="$2"

    host "$vm_name (groups: servers,$groups)"

    if ! incus info "$vm_name" >/dev/null 2>&1; then
        fail "$vm_name does not exist - run 'make test-env-create' first"
        return
    fi

    # 1. Snapshot active timers before the reboot.
    local timers_before
    timers_before="$(active_timers "$vm_name")"

    # 2. Reboot and wait for the VM to come back.
    step "Rebooting $vm_name"
    incus restart "$vm_name" >/dev/null 2>&1

    local attempts=0
    until incus exec "$vm_name" -- true >/dev/null 2>&1; do
        attempts=$((attempts + 1))
        if (( attempts >= AGENT_WAIT_ATTEMPTS )); then
            fail "$vm_name agent did not return after reboot"
            return
        fi
        sleep "$AGENT_WAIT_SLEEP"
    done

    # Wait for systemd to finish booting (running, or degraded if a
    # non-critical unit like smartd failed on virtual hardware).
    attempts=0
    local state=""
    while (( attempts < SETTLE_WAIT_ATTEMPTS )); do
        state="$(vm "$vm_name" systemctl is-system-running 2>/dev/null || true)"
        [[ "$state" == "running" || "$state" == "degraded" ]] && break
        sleep "$SETTLE_WAIT_SLEEP"
        attempts=$((attempts + 1))
    done
    if [[ "$state" == "running" ]]; then
        ok "system booted (is-system-running=running)"
    elif [[ "$state" == "degraded" ]]; then
        warn "system booted but degraded - a non-critical unit failed (checking headline services below)"
    else
        fail "system did not finish booting (is-system-running=$state)"
    fi

    # 3. Headline services: enabled + active.
    step "Checking headline services start on boot"
    local svc
    for svc in $(expected_services_for "$groups"); do
        assert_service "$vm_name" "$svc"
    done

    # 4. Firewall still active (ufw.service is oneshot/inactive by design -
    #    check the framework status, not the unit).
    step "Checking firewall persisted"
    if vm "$vm_name" ufw status 2>/dev/null | grep -q "Status: active"; then
        ok "ufw Status: active"
    else
        fail "ufw is not active after reboot"
    fi

    # 5. Timer persistence: every timer active before must be active again.
    step "Checking timers re-armed after reboot"
    local timers_after missing
    timers_after="$(active_timers "$vm_name")"
    missing="$(comm -23 <(printf '%s\n' "$timers_before") <(printf '%s\n' "$timers_after"))"
    if [[ -z "$missing" ]]; then
        local n
        n="$(printf '%s\n' "$timers_before" | grep -c . || true)"
        ok "all $n previously-active timers re-armed"
    else
        while IFS= read -r t; do
            [[ -n "$t" ]] && fail "timer not re-armed after reboot: $t"
        done <<< "$missing"
    fi
}

# --- Main ---
if [[ ! -r "$VM_CONF" ]]; then
    printf "${RED}Cannot read %s${RESET}\n" "$VM_CONF" >&2
    exit 1
fi

printf "${YELLOW}Reboot persistence check - this restarts every test VM.${RESET}\n"

while IFS=: read -r -u 3 vm_name vm_groups _vm_extra; do
    [[ -z "$vm_name" || "$vm_name" == \#* ]] && continue
    check_vm "$vm_name" "$vm_groups"
done 3< <(grep -v '^\s*#' "$VM_CONF" | grep -v '^\s*$')

printf "\n"
if (( FAILS == 0 )); then
    printf "${GREEN}All reboot-persistence checks passed.${RESET}\n"
else
    printf "${RED}%d check(s) failed.${RESET}\n" "$FAILS"
fi
exit "$FAILS"
