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
- enables `nut.target`, which brings up the driver instances, `upsd` and
  `upsmon`

Low-battery shutdown is performed by `upsmon` through `SHUTDOWNCMD`.

## Variables

| Variable | Default | Description |
|---|---|---|
| `nut_enabled` | `false` | Enable the role |
| `nut_mode` | `standalone` | `standalone`, `netserver` or `netclient` |
| `nut_ups_global_options` | `pollinterval`, `maxretry` | Global `ups.conf` options |
| `nut_ups` | `[]` | List of UPS sections: `name`, `driver`, `port`, `desc` |
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
  - name: greencell
    driver: blazer_usb
    port: auto
    desc: "Green Cell UPS"

nut_monitors:
  - ups: greencell
    host: 127.0.0.1
    powervalue: 1
    user: monuser
    password: "{{ vault_nut_monitor_password }}"
    role: primary
```

## Testing without hardware

`make test-nut` uses the `dummy-ups` driver in the Incus test environment. It
checks the rendered configuration, `nut.target`, `upsc`, the `OL`/`OB`
transition and the `nocomm` grace period without a physical UPS.
