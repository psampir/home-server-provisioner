# smart_monitoring

Disk health monitoring for a Debian 13 host using **smartd**
(`smartmontools`), with alerts routed through `hsp-notify`
(roles/notifications). Deliberately minimal: no Scrutiny, no web UI, no
database - just the daemon and a notification hook.

Enabled by default (`smart_monitoring_enabled: true`) and safe to apply
everywhere: smartd skips devices without SMART support (e.g. virtual
disks) gracefully, and Debian's unit carries `ConditionVirtualization=no`
so it stays dormant inside VMs/containers and only runs on real hardware.

## What it does

1. Installs `smartmontools`.
2. Installs a notification wrapper at `/usr/local/bin/hsp-notify-smartd`
   that formats smartd's `SMARTD_*` environment variables and calls
   `hsp-notify` (urgent priority by default).
3. Writes `/etc/smartd.conf` with a single `DEVICESCAN` line that
   auto-detects every SMART-capable device, enables attribute/offline
   monitoring, schedules self-tests, and runs the wrapper on any alert
   via `-M exec` (`-m root` is required syntactically but no mail is
   sent - `-M exec` replaces the mailer).
4. Enables the `smartmontools` service (and starts it on physical hosts).
5. On configuration change, restarts smartd and sends an informational
   "SMART monitoring active" notice so you can confirm the alert path is
   wired up.

## Self-test schedule

The default `-s (S/../.././02|L/../../6/03)` directive runs:

- a **short** test every day at 02:00, and
- a **long** test every Saturday at 03:00.

Override via `smart_monitoring_devicescan_opts`. The `-s` format is
`T/MM/DD/d/HH` (T = `S`hort or `L`ong; `d` = day of week 1-7).

## Disabling

Set `smart_monitoring_enabled: false` to stop and disable smartd and
remove the managed `/etc/smartd.conf` and wrapper. The `smartmontools`
package is left installed.

## What it does NOT do

- **No dashboard** - for a multi-host SMART dashboard, deploy Scrutiny as
  a separate compose stack (out of scope for this role).
- **No per-device tuning out of the box** - use
  `smart_monitoring_extra_directives` to append raw `smartd.conf` lines
  (e.g. device-specific overrides) if you need them.
- **No mail** - alerts go through `hsp-notify` only.

## Variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `smart_monitoring_enabled` | `true` | Master switch; `false` tears down config + wrapper. |
| `smart_monitoring_devicescan_opts` | `-a -o on -S on -s (...)` | Monitoring + self-test directives applied to every device. |
| `smart_monitoring_extra_directives` | `[]` | Extra raw lines appended to `smartd.conf`. |
| `smart_monitoring_notify_priority` | `urgent` | hsp-notify priority for alerts. |
| `smart_monitoring_notify_tags` | `warning,floppy_disk` | hsp-notify tags for alerts. |
| `smart_monitoring_notify_on_change` | `true` | Send an info notice when the config changes. |

## Dependencies

Requires the `notifications` role (provides `hsp-notify`). With no ntfy
backend configured, `hsp-notify` becomes a no-op that logs to the
journal, so this role is still safe to enable.
