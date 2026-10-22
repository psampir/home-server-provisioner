# journal

Makes the systemd journal persistent across reboots and optionally limits
its size or retention.

## What it does

1. Creates `/var/log/journal` with group `systemd-journal` and mode `2755`.
2. Creates `/etc/systemd/journald.conf.d`.
3. Writes `persistent.conf` with `Storage` and optional limits.
4. Restarts `systemd-journald` through a handler when the file changes.

## Variables

| Variable | Default | Description |
|---|---|---|
| `journal_storage` | `persistent` | `Storage=` value |
| `journal_max_use` | empty | `SystemMaxUse=` value, for example `1G` |
| `journal_max_retention_sec` | empty | `MaxRetentionSec=` value, for example `30day` |

Empty limit values are omitted, so systemd's own defaults apply.

## Notes

- Persistent storage means logs survive a reboot. On a host with a small
  root disk, set `journal_max_use` to cap growth.
- The directory mode `2755` sets the setgid bit so new journal files inherit
  the `systemd-journal` group.
- The role does not vacuum existing logs. Use `journalctl --vacuum-size` or
  `journalctl --vacuum-time` once if you change the limits on a live host.
- The handler restarts `systemd-journald`, which briefly interrupts log
  collection. It does not reboot the host.
