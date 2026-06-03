# scheduled_jobs

systemd timers + matching services for periodic work. Replaces cron in
this project - one scheduling mechanism is enough, and systemd gives us
free wins (journal logging, dependency wiring, `OnFailure=` hooks, ad-hoc
runs via `systemctl start`, monotonic+wall-clock schedules).

## Layout

Job definitions live as Ansible variables, not files. Two lists are
merged at provision time:

- `scheduled_jobs_common` - set in `group_vars/`, shared baseline.
- `scheduled_jobs_host` - set in `host_vars/<host>/`, host-specific.

A job named in `scheduled_jobs_host` overrides one with the same `name` in
`scheduled_jobs_common` (entry-level; no per-field merge).

Each job becomes two units:

- `/etc/systemd/system/sched-<name>.service` - `Type=oneshot`
- `/etc/systemd/system/sched-<name>.timer` - calendar trigger

The `sched-` prefix keeps managed units from colliding with anything
shipped by Debian or installed by hand. The role tracks them in
`/var/lib/home-server-provisioner/scheduled_jobs.manifest`; jobs removed
from the config are cleaned up (timer + service stopped, disabled, unit
files deleted, daemon reloaded) on the next run.

## Job fields

| Field | Required | Default | Purpose |
|---|---|---|---|
| `name` | yes | - | `[a-z0-9-]+`, used as `sched-<name>.{service,timer}` |
| `command` | yes | - | Absolute path to executable + args, becomes `ExecStart=` |
| `schedule` | yes | - | systemd `OnCalendar=` expression |
| `description` | no | `Scheduled job: <name>` | `Description=` on both units |
| `user` | no | `root` | `User=` on the service |
| `group` | no | same as `user` | `Group=` on the service |
| `working_directory` | no | (unset) | `WorkingDirectory=` on the service |
| `environment` | no | `{}` | Dict → `Environment=` lines |
| `log_file` | no | (unset) | Wraps `ExecStart` with `sh -c '… >> <path> 2>&1'`; pre-created `0640 user:group` |
| `persistent` | no | `true` | `Persistent=` on the timer (catch up missed runs) |
| `randomized_delay` | no | (unset) | `RandomizedDelaySec=` |
| `accuracy` | no | (unset) | `AccuracySec=` |
| `notify_on_failure` | no | `true` | Adds `OnFailure=hsp-notify-failure@%n.service` |
| `state` | no | `present` | `present` or `absent` |

## Failure notifications

Every job gets `OnFailure=hsp-notify-failure@%n.service` by default. If
the `notifications` role is configured (`notifications_ntfy_url` set),
a failed run pushes an alert to your phone via ntfy. Without a backend
configured the call is a no-op (logged to the journal under tag
`hsp-notify`), so opting out per-job (`notify_on_failure: false`) is
only needed for jobs you genuinely don't want to hear about.

## Examples

### Nightly borg backup, root, with a log file

```yaml
# host_vars/hsp-app/main.yml
scheduled_jobs_host:
  - name: backup-borg
    description: "Nightly borg backup of /opt/stacks"
    command: /usr/local/bin/backup-borg.sh
    schedule: "*-*-* 03:00:00"
    user: root
    log_file: /var/log/backup-borg.log
    randomized_delay: "10m"
    environment:
      BORG_REPO: "ssh://backup@hsp-backup/./repo"
```

### Common: rotate /var/log/legacy-app, every host, opt-out of alerts

```yaml
# group_vars/all/main.yml
scheduled_jobs_common:
  - name: rotate-legacy-app
    command: /usr/local/bin/rotate-legacy-app
    schedule: "Sun *-*-* 04:00:00"
    notify_on_failure: false
    persistent: false
```

### Retiring a job

Set `state: absent` instead of deleting the entry - keeps the change
visible in your config diff:

```yaml
scheduled_jobs_host:
  - name: backup-borg
    state: absent
```

The role stops the timer + service, disables them, and removes the unit
files on the next run.

## Composing with `custom_scripts`

`scheduled_jobs` only schedules. The script `/usr/local/bin/backup-borg.sh`
above is shipped by the `custom_scripts` role from
`configs/<env>/scripts/{_common,<host>}/`. Reference it by absolute path
in `command:` - there is no implicit linkage.

## Inspecting

```bash
systemctl list-timers 'sched-*'
systemctl status sched-backup-borg.timer
journalctl -u sched-backup-borg.service -n 50
```
