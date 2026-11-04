# auto_updates

Configures unattended security upgrades and optional restart detection.

## What it does

1. Installs `unattended-upgrades` and `apt-listchanges`.
2. Writes `/etc/apt/apt.conf.d/20auto-upgrades` to enable periodic package
   list updates and unattended upgrades.
3. Writes `/etc/apt/apt.conf.d/50unattended-upgrades` with the allowed
   origins, dependency cleanup, dpkg autofix, and optional automatic reboot.
4. Installs and pins `needrestart` to a non-interactive mode so it cannot
   block unattended upgrades.
5. Optionally installs a daily `needrestart -b` timer that calls
   `hsp-notify` when a service or the kernel needs a restart.
6. When automatic reboot is enabled, schedules `shutdown -r <time>` as soon
   as `/run/reboot-required` exists, and installs `hsp-reboot-notify` for a
   warning shortly before the reboot.

## Variables

| Variable | Default | Description |
|---|---|---|
| `auto_updates_origins` | Debian security | Origins upgraded by unattended-upgrades |
| `auto_updates_enable_reboot` | `false` | Enable `Automatic-Reboot` |
| `auto_updates_reboot_time` | `03:00` | Reboot time when enabled |
| `auto_updates_reboot_notify_bin` | `/usr/local/bin/hsp-reboot-notify` | Script that warns about a scheduled reboot |
| `auto_updates_remove_unused_dependencies` | `true` | Remove unused dependencies after upgrades |
| `auto_updates_autofix_interrupted_dpkg` | `true` | Repair interrupted dpkg runs |
| `auto_updates_needrestart` | `true` | Install and configure needrestart |
| `auto_updates_needrestart_mode` | `l` | `l` list, `a` auto-restart, `i` interactive |
| `auto_updates_needrestart_notify` | `true` | Install the daily notify timer |
| `auto_updates_needrestart_notify_schedule` | `*-*-* 07:30:00` | Timer schedule |
| `auto_updates_needrestart_notify_unit` | `sched-needrestart-notify` | Service and timer unit name |
| `auto_updates_notify_bin` | `/usr/local/bin/hsp-notify` | Notification helper |

## Notes

- The default `l` mode never restarts services. It records what needs a
  restart and leaves the decision to the operator. Use `a` only if you
  accept automatic service restarts during an upgrade.
- `i` mode is interactive and can hang unattended-upgrades. The role pins a
  non-interactive mode for that reason.
- The notify timer depends on the `notifications` role to provide
  `hsp-notify`. Without it the timer unit still exists, but the alert cannot
  be delivered.
- Automatic reboot is off by default. When enabled, the role schedules it
  as soon as `/run/reboot-required` exists instead of waiting for the next
  unattended-upgrades run. A kernel update normally needs a reboot before
  the new kernel is active.
- The role does not run `unattended-upgrade` immediately. The timer and APT
  periodic jobs run on their own schedule.

## Automatic reboot

With `auto_updates_enable_reboot: true`, the role runs
`shutdown -r {{ auto_updates_reboot_time }}` as soon as
`/run/reboot-required` exists and no shutdown is already scheduled. That
closes the gap where unattended-upgrades only schedules the reboot on its
next run, which can be up to a day after a kernel install.

Schedule the warning shortly before the reboot time:

```yaml
scheduled_jobs_host:
  - name: reboot-notify
    command: /usr/local/bin/hsp-reboot-notify
    schedule: "*-*-* 02:30:00"
    description: "Warn before the automatic reboot"
    notify_on_failure: true
```

`hsp-reboot-notify` reads `/run/systemd/shutdown/scheduled` and stays silent
unless a reboot is queued within `HSP_REBOOT_NOTIFY_LEAD_MINUTES` (default
60). It never warns about a reboot that is only required, not scheduled.

## Failure notifications

Every unit in `auto_updates_notify_failed_units` (default:
`apt-daily-upgrade.service`) gets a drop-in with
`OnFailure=hsp-notify-failure@%n.service`, so a failed automatic upgrade
reaches the phone instead of stopping at the journal. The drop-in is safe
on hosts without the `notifications` role: `hsp-notify` is inert when no
backend is configured.

Removing a unit from the list deletes its drop-in on the next run.

## Update report

`hsp-update-report` prints the packages apt would upgrade. It is
read-only: no upgrade, no pull, no container touched. Schedule it from
`scheduled_jobs` and let it send the list through `hsp-notify`; decide on a
window with the real list instead of jumping tags to `latest`.

Docker images are deliberately not part of the report. Image age is not
the same as an available update, so images are reviewed manually in a
deliberate window, with the upstream release notes in hand.

| Variable | Default | Description |
|---|---|---|
| `auto_updates_report_bin` | `/usr/local/bin/hsp-update-report` | Script path |
| `auto_updates_report_config` | `/etc/hsp/update-report.conf` | Rendered config |
| `auto_updates_report_max_items` | `15` | Packages listed before "and N more" |

Schedule it from `scheduled_jobs`, monthly:

```yaml
scheduled_jobs_common:
  - name: update-report
    command: /usr/local/bin/hsp-update-report
    schedule: "*-*-01 08:00:00"
    description: "Monthly package update report"
    notify_on_failure: true
```
