# borgmatic

Client/source side of the backup pipeline. Installs **borgmatic** +
**borgbackup**, renders a borgmatic config, and schedules a nightly
`borgmatic create` that **pushes** archives over SSH (through the
WireGuard tunnel) to a borg repository served by the
[`borg_repo`](../borg_repo/README.md) role on a `backup_targets` host.

Pairs with `borg_repo`: this role is the **source**, that role is the
**target**. The two communicate through a single source of truth - the
`borgmatic_repositories` list declared here (usually in `host_vars`).

The role is **inert by default**: with an empty `borgmatic_repositories`
nothing dynamic is installed and any previously managed config is torn
down. Opt in by declaring repositories.

## Security model - append-only

The dedicated SSH key generated here (`/root/.ssh/id_borg`) is authorized
on the target under an **append-only, path-restricted** forced command
(see `borg_repo`). Append-only is borg's defence against a compromised
source: the client may *append* new archives, and a delete it issues only
updates the repository manifest - the underlying **data segments are
physically preserved** and the space-freeing operation (`borg compact`)
is silently refused. So a compromised source can hide archives but
**cannot actually destroy backed-up data**; an admin recovers them with
borg's documented append-only rollback (the per-transaction log is kept
on the server). The classic ransomware "wipe the backups too" move is
therefore blocked.

Because append-only forbids client-side pruning/compaction, **retention
is enforced server-side** by `borg_repo`. This role only ever runs
`borgmatic create`; the packaged `borgmatic.service` is retargeted via a
drop-in.

## Encryption & secrets

- Mode: **`repokey-blake2`** - the encryption key lives *inside the repo*,
  wrapped by a passphrase. Disaster recovery needs only the passphrase.
- The passphrase comes from `borgmatic_passphrase` (set it from
  ansible-vault: `borgmatic_passphrase: "{{ vault_borgmatic_passphrase }}"`)
  and is written to `/etc/borgmatic/borgmatic.env` (mode `0600`), injected
  into the unit via `EnvironmentFile` and referenced from the config as
  `${BORG_PASSPHRASE}`.
- **Keep the passphrase safe out-of-band.** Without it, archives are
  unrecoverable. Do *not* rotate it casually - see `docs/backups.md`.

## What it does (enabled path)

1. Installs `borgbackup` + `borgmatic`.
2. Generates a host-local ed25519 keypair for pushes (regenerable; the
   target re-authorizes it on the next provision).
3. Publishes the public key as a host fact so the `borg_repo` play can
   authorize it.
4. Writes `/etc/borgmatic/borgmatic.env` (passphrase, `0600`) and
   `/etc/borgmatic/config.yaml` (`0600`, schema-validated).
5. Drop-ins on `borgmatic.service` (create-only + `EnvironmentFile` +
   `OnFailure=` notify) and `borgmatic.timer` (schedule).
6. Routes `on_error` (and optionally `after_backup`) to `hsp-notify` via
   `/usr/local/bin/hsp-borgmatic-notify`.
7. Enables `borgmatic.timer`.

## Key variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `borgmatic_source_directories` | `[]` | Absolute paths to back up. Required when repositories set. |
| `borgmatic_repositories` | `[]` | Managed (`target`/`path`/`retention`) or external (`url`) repos. |
| `borgmatic_passphrase` | `"{{ vault_borgmatic_passphrase | default('') }}"` | Repo passphrase. |
| `borgmatic_encryption_mode` | `repokey-blake2` | Borg key mode for managed repo init. |
| `borgmatic_keep_daily/weekly/monthly` | `7 / 4 / 6` | Default retention (enforced by the target). |
| `borgmatic_schedule` | `*-*-* 02:30:00` | Nightly `OnCalendar` for the backup. |
| `borgmatic_notify_on_failure` | `true` | `on_error` → hsp-notify. |
| `borgmatic_notify_on_success` | `false` | `after_backup` → hsp-notify. |
| `borgmatic_exclude_patterns` | `[]` | Borg `--exclude` patterns. |

## Repository entry forms

```yaml
borgmatic_source_directories:
  - /opt/stacks
  - /etc

borgmatic_repositories:
  # Managed target (primary): repo created, key-initialized, authorized
  # and pruned by the borg_repo role on host `hsp-backup`. Final repo path:
  #   /srv/borg/<this_host>/main  on the target.
  - target: hsp-backup
    path: main
    label: offsite
    retention:                # optional; overrides borgmatic_keep_*
      keep_daily: 14
      keep_weekly: 8
      keep_monthly: 12

  # External (escape hatch): a repo you manage yourself. NOT auto-created
  # or pruned by this project - you initialize and maintain it.
  - url: "ssh://user@borgbase-host/./repo"
    label: cloud
```

## Manual operations

Ad-hoc borg/borgmatic commands need the passphrase in the environment:

```bash
set -a; . /etc/borgmatic/borgmatic.env; set +a
borgmatic list                 # archives across all repos
borgmatic rinfo
borg list ssh://borg@10.10.0.3/srv/borg/$(hostname -s)/main
```

Restore flow and passphrase rotation are documented in `docs/backups.md`.

## Dependencies

- The [`borg_repo`](../borg_repo/README.md) role on the target host
  (initializes repos, authorizes keys, enforces retention).
- The `notifications` role (provides `hsp-notify`). With no ntfy backend,
  notifications degrade to journal no-ops, so this role is still safe.
- WireGuard connectivity to the target (backups travel over the tunnel).
