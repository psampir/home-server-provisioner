# Backups (borgmatic + borg)

This project backs up host data with **borgmatic** (a friendly front-end
to **BorgBackup**) in a **push, append-only** topology:

```
  source host                         backup target
 (borgmatic role)                     (borg_repo role)
  /opt/stacks, /etc  --- borg create -->  /srv/borg/<source>/<repo>
        |               (over WireGuard,        ^
        |                SSH append-only)       |
        |                                  borg prune + compact
        |                                  (local, scheduled)
  id_borg keypair  ----- authorized -----> ~borg/.ssh/authorized_keys
                       (forced command:
                        borg serve --append-only
                        --restrict-to-path /srv/borg/<source>)
```

Two roles cooperate:

- **`borgmatic`** (source): what to back up, where to, when. Pushes only.
- **`borg_repo`** (target): hosts the repos, authorizes sources
  append-only, and owns retention (prune + compact).

See each role's README for the full variable reference. This document
covers **operating** the system: restore, monitoring, and the rare
passphrase rotation.

## Design decisions

| Decision | Choice | Why |
| --- | --- | --- |
| Direction | Push from source | Source needs no inbound access; works behind NAT over WireGuard. |
| Server trust | `--append-only` + `--restrict-to-path` per source | A compromised source cannot physically destroy data (deletes stay recoverable) or reach another host's history. |
| Key mode | `repokey-blake2` | Key lives in the repo; disaster recovery needs only the passphrase. |
| Retention | Enforced on the target | Append-only forbids client-side pruning. |
| Secrets | Passphrase in ansible-vault; SSH key host-local | Passphrase must persist for the repo's life; SSH key is regenerable. |
| Scheduling | borgmatic's own `borgmatic.timer` (retargeted) | Use the ecosystem tool; add `OnFailure` + create-only via drop-ins. |

## Configuring backups

In `host_vars/<source>.yml` (or group_vars for a shared baseline):

```yaml
borgmatic_source_directories:
  - /opt/stacks
  - /etc

borgmatic_repositories:
  - target: hsp-backup        # inventory host running the borg_repo role
    path: main                # repo dir under /srv/borg/<source>/
    label: offsite
    retention:
      keep_daily: 14
      keep_weekly: 8
      keep_monthly: 12
```

In `group_vars/all/` (production), point the passphrase at the vault:

```yaml
borgmatic_passphrase: "{{ vault_borgmatic_passphrase }}"
```

Set the secret once:

```bash
make vault-edit ENV=prod      # add: vault_borgmatic_passphrase: "<long random string>"
make provision  ENV=prod
```

Provisioning initializes the repo on the target and authorizes the
source. The first backup runs at the next timer tick - or trigger one
manually (see below).

> **Back up the passphrase out-of-band** (password manager, printed copy
> in a safe). Losing it makes every archive unrecoverable.

## Triggering a backup manually

On the source:

```bash
sudo systemctl start borgmatic.service     # runs the create-only unit
journalctl -u borgmatic.service -n 50
# or directly:
sudo bash -c 'set -a; . /etc/borgmatic/borgmatic.env; set +a; borgmatic create --stats --list'
```

## Listing archives

```bash
# On the source (knows all its repos via the config):
sudo bash -c 'set -a; . /etc/borgmatic/borgmatic.env; set +a; borgmatic list'
sudo bash -c 'set -a; . /etc/borgmatic/borgmatic.env; set +a; borgmatic rinfo'
```

## Restoring data

Borgmatic's `extract` pulls files from an archive into a destination.

```bash
# On the source:
set -a; . /etc/borgmatic/borgmatic.env; set +a

# 1. Find the archive you want:
borgmatic list

# 2. Dry-run extract of a path from a specific archive:
borgmatic extract --archive <archive-name> --path etc/hosts --dry-run

# 3. Extract into a staging dir (paths are relative to '/'):
sudo mkdir -p /restore
borgmatic extract --archive <archive-name> --path opt/stacks \
    --destination /restore

# 4. Inspect /restore, then copy what you need back in place.
```

Restore directly on the target (full local access, e.g. if the source is
gone) - repokey means you only need the passphrase:

```bash
# On hsp-backup:
set -a; . /etc/hsp-borg/borg.env; set +a
sudo -u borg bash -c 'set -a; . /etc/hsp-borg/borg.env; set +a; \
    borg list /srv/borg/<source>/main'
sudo -u borg bash -c 'set -a; . /etc/hsp-borg/borg.env; set +a; \
    borg extract /srv/borg/<source>/main::<archive> etc/hosts'
```

### Restore drill (recommended)

Periodically prove a restore works:

1. Note a known file's content in a backed-up path (e.g. `/etc/hostname`).
2. Extract it to `/restore` and `diff` against the live file.
3. Confirm the timestamps/size match an expected recent archive.

## Retention & space

Retention is applied on the **target** by `hsp-borg-maintenance.timer`
(default daily at 05:00): `borg prune` per the declared policy, then
`borg compact` to reclaim space. Inspect:

```bash
# On the target:
systemctl status hsp-borg-maintenance.timer
journalctl -u hsp-borg-maintenance.service -n 50
sudo -u borg bash -c 'set -a; . /etc/hsp-borg/borg.env; set +a; \
    borg info /srv/borg/<source>/main'
```

## Recovering from a malicious / accidental delete

Append-only guarantees a source can never *physically* destroy data, so
even if a compromised host runs `borg delete` (which only rewrites the
manifest and makes archives "disappear" from `borg list`), the segments
are still on the target. The server keeps a per-transaction log
(`<repo>/transactions`) that lets an admin roll the repository back to the
state before the malicious transaction.

This is a deliberate, manual operation - borg ships the procedure upstream
(see *"append-only mode"* in the BorgBackup docs). Do **not** run
`borg compact` first: compaction is what would finally free the orphaned
segments, and it is exactly what append-only refuses for a source. From a
local (non-restricted) shell on the target, follow borg's documented
rollback to restore the manifest, then verify with `borg list` / `borg
check`.

## Monitoring

- Backup failures: borgmatic's `on_error` hook calls `hsp-notify`
  (`borgmatic_notify_on_failure: true`), plus `OnFailure=` on the unit.
- Optional success pings: `borgmatic_notify_on_success: true`.
- Maintenance failures: `OnFailure=` on `hsp-borg-maintenance.service`.

With no ntfy backend configured these degrade to journal no-ops - wire up
the `notifications` role to get phone pushes.

## Passphrase rotation (rare)

Changing the passphrase only re-wraps the repo key - it does **not**
re-encrypt data and does **not** invalidate existing archives. But under
append-only the change must be made from a non-restricted context
(the target has local access). It is rarely needed.

```bash
# 1. On the target, for each repo, change the passphrase (needs OLD + NEW):
sudo -u borg bash -c '
  export BORG_PASSPHRASE="<OLD>" BORG_NEW_PASSPHRASE="<NEW>"
  borg key change-passphrase /srv/borg/<source>/main'

# 2. Update the secret in the vault:
make vault-edit ENV=prod      # set vault_borgmatic_passphrase: "<NEW>"

# 3. Re-provision so /etc/borgmatic/borgmatic.env and /etc/hsp-borg/borg.env
#    pick up the new value on every host:
make provision ENV=prod
```

Do all repos that share the passphrase in the same pass.

## Disabling backups for a host

Remove (or empty) `borgmatic_repositories` for the host and re-provision:
the source's config + timer are torn down. The repo and its archives on
the target are intentionally **left intact** (deleting backups is never
automatic).

## Test environment

`make test-env-create` provisions **five** VMs (`scripts/test-vms.conf`):

| VM | Groups | `vpn_ip` |
| --- | --- | --- |
| `hsp-vpn` | `vpn_server` (hub) | `10.10.0.1` |
| `hsp-app` | `app_servers` | `10.10.0.2` |
| `hsp-backup` | `backup_targets` | `10.10.0.3` |
| `hsp-app2` | `app_servers` | `10.10.0.4` |
| `hsp-backup2` | `backup_targets` | `10.10.0.5` |

`hsp-app` pushes `/etc` to **two** independent repos over WireGuard -
`hsp-backup` (`primary`) and `hsp-backup2` (`offsite`) - and `hsp-app2`
pushes to `hsp-backup` as well. That exercises multi-target sources and
multi-source targets in one run: key authorization, append-only push,
repo init, and server-side prune.

```bash
make test-env-create
make test-bootstrap
make test-provision           # provisions all five VMs
make test-provision           # second run: changed=0 (idempotent)

# Verify on hsp-app:
incus exec hsp-app -- systemctl start borgmatic.service
incus exec hsp-app -- bash -c 'set -a; . /etc/borgmatic/borgmatic.env; set +a; borgmatic list'
# Verify on hsp-backup:
incus exec hsp-backup -- ls -la /srv/borg/hsp-app/main
```
