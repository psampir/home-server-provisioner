#!/usr/bin/env bash
#
# Test the nut role against the Incus test environment using the dummy-ups
# driver. No physical UPS is required.
#
# Usage: scripts/test-nut.sh [host]   (default: hsp-app)

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
HOST="${1:-hsp-app}"
INVENTORY="$REPO_ROOT/configs/test/inventory"
VAULT_PASS="$REPO_ROOT/configs/test/.vault_pass"
PLAYBOOK="$REPO_ROOT/playbooks/nut_test.yml"
TMPDIR="$(mktemp -d /tmp/opencode/nut-test.XXXXXX)"
trap 'rm -rf "$TMPDIR"' EXIT

fail() { echo "FAIL: $*" >&2; exit 1; }
pass() { echo "PASS: $*"; }

[[ -f "$INVENTORY/hosts.yml" ]] || fail "$INVENTORY/hosts.yml not found; run make test-env-create"
[[ -f "$VAULT_PASS" ]] || fail "$VAULT_PASS not found"
[[ -f "$PLAYBOOK" ]] || fail "$PLAYBOOK not found"

incus info "$HOST" >/dev/null 2>&1 || fail "Incus instance $HOST not found"

echo "==> preparing $HOST"
incus exec "$HOST" -- bash -c '
set -e
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq nut >/dev/null
install -d -o root -g nut -m 0755 /etc/nut
cat > /etc/nut/dummy.dev <<EOF
ups.status: OL
battery.charge: 100
ups.load: 10
ups.temperature: 25
EOF
# The previous run may have left the driver active with an OB/FSD state from
# the transition tests. Reload the freshly written OL state when it is
# already running; the role starts it later when it is not. upsd also keeps
# an FSD flag from the previous run, so restart it as well.
systemctl try-restart nut-driver@dummy.service || true
systemctl try-restart nut-server.service || true
'

cat > "$TMPDIR/vars.yml" <<'EOF'
nut_enabled: true
nut_ups:
  - name: dummy
    driver: dummy-ups
    port: /etc/nut/dummy.dev
    desc: "test UPS"
nut_monitors:
  - ups: dummy
    host: 127.0.0.1
    powervalue: 1
    user: monuser
    password: testmon
    role: primary
nut_users:
  - name: admin
    password: testadmin
    actions: SET
    instcmds: ALL
  - name: monuser
    password: testmon
    upsmon: primary
nut_shutdown_command: /bin/true
nut_nocomm_shutdown_command: /bin/true
nut_nocomm_grace_seconds: 3
nut_nocomm_poll_seconds: 1
EOF

echo "==> applying the role"
ANSIBLE_VAULT_PASSWORD_FILE="$VAULT_PASS" ansible-playbook "$PLAYBOOK" \
  -i "$INVENTORY" -l "$HOST" -e "@$TMPDIR/vars.yml" >"$TMPDIR/apply.log"
tail -3 "$TMPDIR/apply.log"

echo "==> checking idempotence"
ANSIBLE_VAULT_PASSWORD_FILE="$VAULT_PASS" ansible-playbook "$PLAYBOOK" \
  -i "$INVENTORY" -l "$HOST" -e "@$TMPDIR/vars.yml" >"$TMPDIR/apply2.log"
grep -q 'changed=0' "$TMPDIR/apply2.log" || fail "second run was not idempotent"
pass "role is idempotent"

[[ "$(incus exec "$HOST" -- systemctl is-active nut.target)" == "active" ]] \
  || fail "nut.target is not active"
pass "nut.target is active"

upsc_out=""
for _ in 1 2 3 4 5 6 7 8 9 10; do
  if upsc_out="$(incus exec "$HOST" -- upsc dummy 2>/dev/null)"; then break; fi
  sleep 1
done
grep -q 'ups.status: OL' <<<"$upsc_out" || fail "upsc did not report OL"
pass "upsc reports OL"

incus exec "$HOST" -- ss -ltn | grep -q '127.0.0.1:3493' \
  || fail "upsd is not listening on 3493"
pass "upsd listens on 127.0.0.1:3493"

mode="$(incus exec "$HOST" -- stat -c '%a %U:%G' /etc/nut/upsd.users)"
[[ "$mode" == "640 root:nut" ]] || fail "upsd.users mode is $mode"
pass "upsd.users is 640 root:nut"

echo "==> simulating OL -> OB"
incus exec "$HOST" -- sed -i 's/^ups.status: OL/ups.status: OB/' /etc/nut/dummy.dev
incus exec "$HOST" -- systemctl restart nut-driver@dummy.service
upsc_out=""
for _ in 1 2 3 4 5 6 7 8 9 10; do
  if upsc_out="$(incus exec "$HOST" -- upsc dummy 2>/dev/null)" && grep -q 'ups.status: OB' <<<"$upsc_out"; then
    break
  fi
  sleep 1
done
grep -q 'ups.status: OB' <<<"$upsc_out" || fail "upsc did not report OB after the transition"
pass "OL -> OB transition works"

echo "==> testing upssched-cmd"
incus exec "$HOST" -- /etc/nut/upssched-cmd online
sleep 1
incus exec "$HOST" -- journalctl -t upssched --no-pager -n 20 | grep -q 'UPS on line power' \
  || fail "upssched-cmd online did not log"
pass "upssched-cmd logs online"

incus exec "$HOST" -- /etc/nut/upssched-cmd nocomm
sleep 1
incus exec "$HOST" -- journalctl -t upssched --no-pager -n 20 | grep -q 'Communication restored' \
  || fail "upssched-cmd nocomm did not detect restoration"
pass "upssched-cmd detects restored communication"

incus exec "$HOST" -- systemctl stop nut-driver@dummy.service
incus exec "$HOST" -- /etc/nut/upssched-cmd nocomm
sleep 1
incus exec "$HOST" -- journalctl -t upssched --no-pager -n 20 | grep -q 'not restored' \
  || fail "upssched-cmd did not expire the grace period"
pass "upssched-cmd expires the grace period"

echo "All NUT tests passed."
