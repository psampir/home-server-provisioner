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

## Custom hook commands

Three opt-in lists add your own commands to borgmatic's command hooks:

| Variable | Hook | Runs |
| --- | --- | --- |
| `borgmatic_before_backup_commands` | `before_backup` | Before each repository's backup. |
| `borgmatic_after_backup_commands` | `after_backup` | After each repository's backup. |
| `borgmatic_on_error_commands` | `on_error` | On an error during create/prune/compact/check or a hook. |

User commands are appended **after** the built-in `hsp-notify` entries, and
a hook key is emitted only when the combined list is non-empty - with the
lists left at `[]` the rendered config is unchanged.

They exist mainly for **containerised databases**. borgmatic's native
`postgresql_databases:` support cannot `docker exec` into a container, so
those databases would otherwise be archived as raw files copied from a live
server. Dump them first and let the dump join the archive:

```yaml
# host_vars/<app-host>.yml
borgmatic_source_directories:
  - /opt/stacks
  - /etc
  - /var/backups/db          # also receives the dumps below

borgmatic_before_backup_commands:
  - /usr/local/bin/hsp-pg-dump
borgmatic_after_backup_commands:
  - rm -f /var/backups/db/*.sql
```

```bash
#!/bin/sh
# /usr/local/bin/hsp-pg-dump - consistent dumps of containerised databases.
set -eu
stage=/var/backups/db
mkdir -p "$stage"
docker exec immich_postgres pg_dumpall -U postgres > "$stage/immich.sql"
docker exec joplin-db       pg_dumpall -U joplin  > "$stage/joplin.sql"
```

The hooks run as root, once per repository, so the script must be
idempotent. The staging directory is deliberately in
`borgmatic_source_directories` so the dump is archived; cleaning it up in
`after_backup` (as above) stops a stale copy being re-archived next run.

These are the classic top-level borgmatic hook keys (`before_backup`,
`after_backup`, `on_error`), which is what borgmatic 1.9 - the version in
Debian 13 - accepts and validates. Newer borgmatic 2.x replaced them with a
`commands:` section; if the role's package ever moves to 2.x, that block
needs migrating.

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
| `borgmatic_before_backup_commands` | `[]` | Extra `before_backup` hook commands. |
| `borgmatic_after_backup_commands` | `[]` | Extra `after_backup` hook commands. |
| `borgmatic_on_error_commands` | `[]` | Extra `on_error` hook commands. |
| `borgmatic_remote_repo_base` | `/srv/borg` | Fallback target repo base when the target host does not define `borg_repo_base`. |
| `borgmatic_exclude_patterns` | `[]` | Borg `--exclude` patterns. |

## Repository entry forms

```yaml
borgmatic_source_directories:
  - /opt/stacks
  - /etc

borgmatic_repositories:
  # Managed target (primary): repo created, key-initialized, authorized
  # and pruned by the borg_repo role on host `hsp-backup`. Final repo path:
  #   <borg_repo_base>/<this_host>/main  on the target, where borg_repo_base
  #   is the target's setting (default /srv/borg).
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

## Relocating the repository base

By default the target keeps every repo under `/srv/borg`. To put them
elsewhere (a big data disk, a separate pool), set **`borg_repo_base` in the
inventory** - `group_vars/all/` so both sides see it:

```yaml
# group_vars/all/main.yml
borg_repo_base: /mnt/HDD/borg
```

The source builds its push URL from the *target's* `borg_repo_base`, read
out of `hostvars`, so it always pushes to the path the target authorises in
its append-only forced command and serves. `borgmatic_remote_repo_base`
(default `/srv/borg`) is only the fallback used when the target does not
define `borg_repo_base`.

Keep it in the inventory rather than in a role's `defaults/`: role defaults
do not cross play boundaries. `borgmatic` renders in the early `servers`
play while `borg_repo` runs in the later `backup_targets` play, so a value
set only in a role's defaults is invisible at render time. The source would
push to `/srv/borg` while the target serves `/mnt/HDD/borg`, and the backup
would fail (or, worse, quietly land nowhere) with no config error.

Give it as an absolute path with no trailing slash - the template appends
`/<source-host>/<repo-path>` verbatim.

Relocating a base that already holds archives means moving the directory on
the target *and* updating the inventory in the same change; borg keys its
cache on the repository URL, so the source may need
`relocated_repo_access_is_ok: true` once afterwards. Setting the base before
the first backup avoids the issue entirely.

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
