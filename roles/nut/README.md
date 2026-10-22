# nut

Network UPS Tools for a single locally attached UPS.

## What it does

- installs the Debian `nut` package (client and server)
- renders `/etc/nut/nut.conf`, `ups.conf`, `upsd.conf`, `upsd.users`,
  `upsmon.conf` and `upssched.conf`
- installs `upssched-cmd`, which logs UPS events to the journal and shuts the
  host down if communication with the UPS is not restored within
  `nut_nocomm_grace_seconds`
- enables `nut.target`, which brings up the driver, `upsd` and `upsmon`

Low-battery shutdown is performed by `upsmon` through `SHUTDOWNCMD`. The role
does not send external notifications; add a notifier later if needed.

## Variables

| Variable | Default | Description |
|---|---|---|
| `nut_enabled` | `false` | Enable the role on the host connected to the UPS |
| `nut_mode` | `standalone` | Value of `MODE` in `nut.conf` |
| `nut_ups_name` | `ups` | Section name in `ups.conf` and `MONITOR` target |
| `nut_ups_driver` | `usbhid-ups` | NUT driver, e.g. `blazer_usb` for many Green Cell units |
| `nut_ups_port` | `auto` | Driver port |
| `nut_ups_desc` | `""` | Optional description |
| `nut_listen_address` | `127.0.0.1` | `upsd` listen address |
| `nut_listen_port` | `3493` | `upsd` listen port |
| `nut_admin_user` | `admin` | User allowed to run `SET` and all instant commands |
| `nut_monitor_user` | `monuser` | User used by `upsmon` |
| `nut_monitor_role` | `primary` | `primary` (NUT 2.8) or `master` (deprecated) |
| `nut_shutdown_command` | `/sbin/shutdown -h +0` | `SHUTDOWNCMD` |
| `nut_nocomm_grace_seconds` | `300` | Grace period after losing communication |
| `nut_nocomm_poll_seconds` | `10` | Poll interval during the grace period |

## Secrets

`nut_admin_password` and `nut_monitor_password` are read from
`vault_nut_admin_password` and `vault_nut_monitor_password`. The role fails
early if either is empty.

## Example

```yaml
nut_enabled: true
nut_ups_name: greencell
nut_ups_driver: blazer_usb
nut_ups_port: auto
nut_ups_desc: "Green Cell UPS"
```
