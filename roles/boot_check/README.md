# boot_check

Post-boot smoke check for hosts with extra data filesystems. It verifies
that the configured mounts are active on the expected device, that Docker
waits for them, and that every running container's bind mounts resolve to
the data filesystem rather than the underlying root-fs directory.

Disabled by default. Enable it on hosts with removable or late mounts;
`boot_check_docker` is only relevant where Docker runs.

## What it does

1. Installs `/usr/local/bin/hsp-boot-check` and
   `/etc/hsp/boot-check.conf`.
2. Installs `hsp-boot-check.service` (oneshot) and
   `hsp-boot-check.timer`: `OnBootSec=2min` and daily at `05:00`,
   `Persistent=true`.
3. Checks each `boot_check_mounts` entry:
   - `findmnt` shows the mountpoint;
   - the source resolves to the configured device (by-id/by-uuid is fine);
   - the filesystem's `MAJ:MIN` differs from `/`, so it is not the root fs.
4. When `boot_check_docker` is true:
   - `docker.service` has `RequiresMountsFor` and is ordered after the
     mount unit;
   - every running container's bind mount from the data path has the
     expected `MAJ:MIN` in `/proc/<pid>/mountinfo`;
   - if the daemon started before the mount (for example the drop-in was
     installed after that boot), a note is printed but the check does not
     fail: the dependency is what guarantees the next boot.
5. On failure it sends an urgent ntfy message through `hsp-notify` and
   exits non-zero. A missing mount is retried for
   `boot_check_retry_seconds`; a stale container bind is reported
   immediately.

## Variables

| Variable | Default | Description |
|---|---|---|
| `boot_check_enabled` | `false` | Install and enable the check |
| `boot_check_mounts` | `[]` | List of `{path, source}` mounts to verify |
| `boot_check_docker` | `false` | Check Docker ordering and container binds |
| `boot_check_retry_seconds` | `120` | Wait for a late mount before failing |
| `boot_check_notify_bin` | `hsp-notify` | Notification helper |
| `boot_check_notify_priority` | `urgent` | ntfy priority |
| `boot_check_notify_tags` | `boot,floppy_disk` | ntfy tags |
| `boot_check_healthchecks_url` | empty | External heartbeat ping URL; kept in Vault |

## Example

```yaml
boot_check_enabled: true
boot_check_mounts:
  - path: /srv/data
    source: /dev/disk/by-id/usb-Seagate_Expansion_XXXX-0:0-part1
boot_check_docker: true   # only on the Docker host
```

Run it by hand:

```bash
sudo systemctl start hsp-boot-check.service
journalctl -u hsp-boot-check.service -n 30 --no-pager
```

The timer runs after every boot and daily, so a container restarted with a
stale bind later is caught too. The check does not restart Docker; it only
reports the problem. Use OliveTin or a manual run to repair it.

## Heartbeat

`boot_check_healthchecks_url` is optional. When set, the script pings the
URL after **every** run, including a failed one. The external service is
therefore a dead-man's switch for "the check did not run", not a second
failure channel: actual failures still go to ntfy immediately. The URL is
stored in Vault and rendered into `/etc/hsp/boot-check.conf`, which is
mode `0600`.

## Limitations

- The check expects exact mount paths; nested bind mounts are matched by
  their Docker destination and the mount's `MAJ:MIN`, so ordinary stack
  mounts are covered.
- A very slow USB disk may need a larger `boot_check_retry_seconds`.
- Gatus heartbeat is not wired yet; the alert goes directly through ntfy.
