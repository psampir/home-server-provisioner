# systemd_units

Drop fully-formed systemd unit files (`.service`, `.timer`, `.socket`,
`.target`, `.mount`, `.path`, `.slice`) from your config tree onto
managed hosts. Treat this as the **escape hatch** for cases the
opinionated `scheduled_jobs` role can't express - long-running daemons,
custom socket activation, multi-instance template units,
[Type=oneshot] one-offs with bespoke directives, etc.

For typical scheduled work (run X every Y minutes), prefer
`scheduled_jobs` - it's smaller, validated, and auto-injects
`OnFailure=hsp-notify-failure@%n.service` for you.

## Layout

```
configs/<env>/systemd/
├── _common/                      # applied to every host
│   ├── my-daemon.service
│   └── my-daemon.timer
└── <inventory_hostname>/         # host-specific overlay (wins on basename)
    └── my-daemon.service         # overrides _common version on this host
```

Subdirectories under `_common/` and the host dir are not recursed -
unit files must sit at the top level.

## What it does

For each host:

1. Collects unit files from `_common/` then `<host>/`. On a basename
   collision, the host file wins.
2. Copies each effective unit to `/etc/systemd/system/` with mode
   `0644`, owner/group `root`.
3. Removes stale units that were managed by a previous run but are no
   longer in the source tree (per-host manifest at
   `/var/lib/home-server-provisioner/systemd_units.manifest`). Stops
   and disables them first when possible.
4. Reloads systemd, then runs `systemd-analyze verify` against every
   managed unit. Findings are printed as warnings; they never fail the
   play (so you can ship a `.timer` referencing a `.service` that's
   only valid once another role has rendered something else).
5. Enables every non-template unit. Starts them **only on the run that
   installed or changed their file** - never on subsequent plays. This
   is deliberate (see "Idempotency notes" below).

**Template units (`foo@.service`)** are installed but never enabled or
started - they only do useful work once instantiated as
`foo@instance.service` by something else (for example, a timer or an
`OnFailure=` reference from another unit).

## Variables

All variables are prefixed `systemd_units_` (per ansible-lint
`var-naming` convention).

| Variable                          | Default                                                | Notes |
|-----------------------------------|--------------------------------------------------------|-------|
| `systemd_units_src_root`          | `{{ inventory_dir }}/../systemd`                       | Set to empty string to disable the role for a host (manifest cleanup still runs). |
| `systemd_units_common_subdir`     | `_common`                                              | |
| `systemd_units_host_subdir`       | `{{ inventory_hostname }}`                             | |
| `systemd_units_install_dir`       | `/etc/systemd/system`                                  | Don't change unless you know why. |
| `systemd_units_manifest_path`     | `/var/lib/home-server-provisioner/systemd_units.manifest` | |
| `systemd_units_auto_enable`       | `true`                                                 | Set to `false` per-host to install files but skip enable+start (useful for staging). |
| `systemd_units_supported_suffixes`| see `defaults/main.yml`                                | Files with other extensions are silently ignored. |

## Failure notifications (manual)

Unlike `scheduled_jobs`, this role does **not** auto-inject
`OnFailure=hsp-notify-failure@%n.service` - your unit file is shipped
verbatim. Add the directive yourself in the `[Unit]` section if you
want a notification when the unit goes into `failed` state:

```ini
[Unit]
Description=My background daemon
After=network-online.target
OnFailure=hsp-notify-failure@%n.service

[Service]
Type=simple
ExecStart=/usr/local/bin/my-daemon
Restart=on-failure
```

The `hsp-notify-failure@.service` template is provided by the
`notifications` role and works for any unit name.

## Idempotency notes

* **Start happens only on first install or file change.** A `state:
  started` on every play would re-trigger every `Type=oneshot` unit
  (they're `inactive` between invocations) and report spurious
  `changed=…` for them. The role registers the copy task and only
  starts units whose file was actually written this run.
* **No auto-restart on change.** Updating a `Type=simple` daemon's
  `ExecStart` ships the new file, but the running process keeps going
  with the old one. Run `systemctl restart <name>` (or roll the host)
  to cut over. This is on purpose - provisioning shouldn't bounce
  long-running services without explicit operator intent.
* **Removing a unit** from the source tree on the next run: stops it,
  disables it, deletes the file, runs `daemon-reload`. If the unit is
  in `failed` state the stop is a no-op; the disable + remove still
  succeed.

## Composition

* `notifications` - required for the suggested `OnFailure=` recipe to
  do anything useful.
* `custom_scripts` - runs **before** `systemd_units` in `site.yml`, so
  `ExecStart=/usr/local/bin/<your-script>` references resolve on the
  first apply.
* `scheduled_jobs` - orthogonal: prefer it for cron-replacement use
  cases. Use `systemd_units` for everything else.
