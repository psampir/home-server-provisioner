# nut

Network UPS Tools on Debian 13 with systemd. Supports one or more UPS
sections, custom users, custom `MONITOR` lines, `standalone`/`netserver`/
`netclient` modes and optional notification hooks.

## What it does

- installs the Debian `nut` package (client and server)
- renders `/etc/nut/nut.conf`, `ups.conf`, `upsd.conf`, `upsd.users`,
  `upsmon.conf` and `upssched.conf` from list-based variables
- installs `upssched-cmd`, which logs UPS events, optionally forwards them
  through a notification command, and shuts the host down if communication
  with every configured UPS is not restored within `nut_nocomm_grace_seconds`
- generates a USB udev rule for every `nut_ups` entry with a USB driver and
  `vendorid`/`productid`, so the driver can open the device as the `nut`
  user
- enables `nut.target`, which brings up the driver instances, `upsd` and
  `upsmon`
- verifies every configured UPS with `upsc` and fails with a clear message
  when it is not reachable

Low-battery shutdown is performed by `upsmon` through `SHUTDOWNCMD`.

## USB permissions

A UPS attached over USB is normally root-owned with restrictive
permissions. `blazer_usb` and friends then fail with `insufficient
permissions` even though the device is present. Declare the USB ids in
`nut_ups`:

```yaml
nut_ups:
  - name: main-ups
    driver: blazer_usb
    port: auto
    vendorid: "0001"
    productid: "0000"
```

The role renders `/etc/udev/rules.d/99-nut-usbups.rules` with:

```text
SUBSYSTEM=="usb", ATTR{idVendor}=="0001", ATTR{idProduct}=="0000", MODE="0660", GROUP="nut"
```

On change it reloads the udev rules, re-triggers USB devices and restarts
NUT, in that order. The `99-` prefix makes the file win over the
distribution's `62-nut-usbups.rules`.

Use `nut_udev_rules` for extra devices that are not in `nut_ups` (a UPS
monitored in `netclient` mode, for example). Each entry takes `vendorid`,
`productid` and optionally `mode` and `group`. Drivers without USB ids
(`dummy-ups`, serial drivers) never generate a rule.

## Verification

After `nut.target` starts, the role runs `upsc <name>` for every `nut_ups`
entry with `nut_verify_retries` retries and `nut_verify_delay` seconds
between them. If a UPS still does not answer, the role fails with the
driver unit name and a pointer to the USB permission check.

Set `nut_verify_ups: false` when upsd is not expected to answer yet, for
example a `netclient` whose remote server starts later.

## Variables

| Variable | Default | Description |
|---|---|---|
| `nut_enabled` | `false` | Enable the role |
| `nut_mode` | `standalone` | `standalone`, `netserver` or `netclient` |
| `nut_ups_global_options` | `pollinterval`, `maxretry` | Global `ups.conf` options |
| `nut_ups` | `[]` | List of UPS sections: `name`, `driver`, `port`, `desc`, optional `vendorid`, `productid`, `subdriver` |
| `nut_udev_usb_drivers` | `blazer_usb`, `nutdrv_qx`, `usbhid-ups` | Drivers that get a generated udev rule |
| `nut_udev_rules` | `[]` | Extra udev rules: `vendorid`, `productid`, optional `mode`, `group` |
| `nut_udev_rules_dir` | `/etc/udev/rules.d` | Destination directory for the generated rule |
| `nut_udev_rules_file` | `99-nut-usbups.rules` | Generated rule filename |
| `nut_udev_rule_mode` | `0660` | Default mode for generated rules |
| `nut_udev_rule_group` | `nut` | Default group for generated rules |
| `nut_verify_ups` | `true` | Verify every UPS with `upsc` after starting NUT |
| `nut_verify_retries` | `10` | `upsc` retries before failing |
| `nut_verify_delay` | `3` | Seconds between `upsc` retries |
| `nut_listen` | `127.0.0.1:3493` | List of `upsd` listen addresses |
| `nut_users` | admin, monuser | List of `upsd.users` entries |
| `nut_monitors` | `[]` | List of `MONITOR` entries for `upsmon.conf` |
| `nut_shutdown_command` | `/sbin/shutdown -h +0` | `SHUTDOWNCMD` |
| `nut_min_supplies` | `1` | `MINSUPPLIES` |
| `nut_poll_freq` | `5` | `POLLFREQ` |
| `nut_poll_freq_alert` | `5` | `POLLFREQALERT` |
| `nut_notify_flags` | ONLINE/ONBATT/LOWBATT/NOCOMM | `NOTIFYFLAG` map |
| `nut_upssched_rules` | NOCOMM | `AT` rules for `upssched.conf` |
| `nut_notify_command` | `""` | Optional command prefix, receives the message as one argument |
| `nut_nocomm_grace_seconds` | `300` | Grace period after losing communication |
| `nut_nocomm_poll_seconds` | `10` | Poll interval during the grace period |
| `nut_nocomm_shutdown_command` | `/sbin/shutdown -h now` | Shutdown command after the grace period |

## Secrets

The default users read `vault_nut_admin_password` and
`vault_nut_monitor_password`. The role fails early if a user or monitor has an
empty password.

## Example

```yaml
nut_enabled: true

nut_ups:
  - name: main-ups
    driver: blazer_usb
    port: auto
    vendorid: "0001"
    productid: "0000"
    desc: "Main UPS"

nut_monitors:
  - ups: main-ups
    host: 127.0.0.1
    powervalue: 1
    user: monuser
    password: "{{ vault_nut_monitor_password }}"
    role: primary
```

## Testing without hardware

`make test-nut` uses the `dummy-ups` driver in the Incus test environment. It
checks the rendered configuration, `nut.target`, `upsc`, the `OL`/`OB`
transition and the `nocomm` grace period without a physical UPS. `dummy-ups`
has no USB ids, so no udev rule is rendered in that test.
