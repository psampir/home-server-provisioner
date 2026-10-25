# borg_repo

Server/target side of the backup pipeline. Runs on `backup_targets`
hosts. Hosts one borg repository per source host, authorizes each
source's SSH key under an **append-only, path-restricted** forced
command, and owns **server-side retention** (prune + compact).

Pairs with [`borgmatic`](../borgmatic/README.md): that role is the
**source**, this one is the **target**.

The role is **data-driven by the sources** - it scans every inventory
host's `borgmatic_repositories` for entries whose `target` is this host.
Nothing is declared here directly; if no source targets the host, the
role is inert.

## What it does

For each source host that targets this server (matched via the published
`borgmatic_ssh_pubkey` fact and a `target:` entry):

1. Creates a system `borg` user (real shell - sshd runs the forced
   command via the login shell) and `<borg_repo_base>/<source>/` repo dirs
   (`/srv/borg` by default).
2. Writes `~borg/.ssh/authorized_keys` with **one line per source**:

   ```
   command="borg serve --append-only --restrict-to-path /srv/borg/<source>",restrict <pubkey>
   ```

   `--append-only` prevents the source from *physically* destroying data
   (a delete it issues only rewrites the manifest; the underlying segments
   are preserved and `borg compact` is refused, so history stays
   recoverable by an admin); `--restrict-to-path` confines each source to
   its own subtree; `restrict` disables port/agent/pty forwarding. Defence
   in depth.
3. Initializes each managed repo **locally** (full access, no append-only
   restriction) with `borg init --encryption repokey-blake2`, using the
   shared passphrase. Sources then open the same repo with the same
   passphrase and only ever append.
4. Installs a local maintenance job - `hsp-borg-maintenance.timer` →
   `borg prune` + `borg compact` per repo - that enforces retention with
   full local access. Failures fire `OnFailure=hsp-notify-failure@%n`.
5. Installs a separate monthly integrity pass -
   `hsp-borg-check.timer` → `borg check` per repo. It reads archive
   manifests, so it is kept off the nightly prune/compact window.
   `--verify-data` stays disabled by default because decrypting and hashing
   every chunk of a multi-terabyte repository takes hours; enable it only
   for a manual restore drill.

## Why the target prunes

Append-only deliberately forbids the source from deleting anything, so
client-side `borgmatic prune` would fail and retention would never be
applied - the repo would grow forever. The authoritative prune therefore
runs here, locally, where there is no append-only restriction. This is
the standard architecture for append-only borg.

## Relocating the repository base

Repos live under `borg_repo_base` (`/srv/borg` by default). To put them on
a data disk, set it in the **inventory**, not in this role's defaults:

```yaml
# group_vars/all/main.yml
borg_repo_base: /mnt/HDD/borg
```

Both sides must agree on the path, and only an inventory variable is visible
to both: the `borgmatic` role renders the sources' push URLs in an earlier
play and reads `borg_repo_base` back from `hostvars`, while a role default
never leaves this role. With the value in `group_vars` the sources push to
exactly the subtree this role creates, authorises
(`--restrict-to-path`) and prunes. See
[`borgmatic`](../borgmatic/README.md#relocating-the-repository-base) for the
source-side view.

## Encryption & secrets

- `borg_repo_passphrase` defaults to `borgmatic_passphrase` (the same
  single secret the sources use), from ansible-vault in production.
- Stored at `/etc/hsp-borg/borg.env` (`0600`), loaded by the maintenance
  unit via `EnvironmentFile`. Also handy for manual admin restore/list:
  `set -a; . /etc/hsp-borg/borg.env; set +a`.

## Variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `borg_repo_passphrase` | `"{{ borgmatic_passphrase | default(...) }}"` | Repo passphrase (init + prune). |
| `borg_repo_encryption_mode` | `repokey-blake2` | `borg init` key mode. |
| `borg_repo_keep_daily/weekly/monthly` | `7 / 4 / 6` | Retention fallback when a source omits `retention:`. |
| `borg_repo_maintenance_schedule` | `*-*-* 05:00:00` | Prune+compact `OnCalendar`. |
| `borg_repo_check_schedule` | `*-*-01 06:00:00` | Integrity check `OnCalendar`. |
| `borg_repo_check_verify_data` | `false` | Add `--verify-data` to the check (hours of I/O, manual drills only). |
| `borg_repo_check_repository_only` | `false` | Add `--repository-only`, skipping archive checks. |
| `borg_repo_base` | `/srv/borg` | Parent dir; one subdir per source host. Set in inventory if relocated. |
| `borg_repo_user` / `borg_repo_group` | `borg` | Repo-serving identity. |

## Scoped runs and `--limit`

The role discovers sources from `borgmatic_repositories`, but it can only
authorise a source whose `borgmatic_ssh_pubkey` fact was published by the
`borgmatic` role in the same play. A limit that excludes the sources hides
that fact.

A run that skips every declared source fails with an explanatory message
instead of silently disabling the role and leaving backups unauthorised.
When only some sources are skipped, the role warns and continues with the
rest. In both cases, include the target and its sources:

```bash
ansible-playbook playbooks/site.yml -i inventory \
  --limit 'backup-host,source-a,source-b'
```

## Retention as a source property

Each source declares retention per repo in its own
`borgmatic_repositories` entry (`retention: { keep_daily, keep_weekly,
keep_monthly }`); this role reads it via `hostvars` and applies it. A
single source of truth lives with the repo owner. Entries that omit it
fall back to `borg_repo_keep_*`.

## Dependencies

- The [`borgmatic`](../borgmatic/README.md) role on source hosts (runs
  earlier in `site.yml`, publishing `borgmatic_ssh_pubkey` facts this role
  consumes).
- The `notifications` role (provides `hsp-notify` for failure alerts).
- WireGuard connectivity (sources reach this host's `vpn_ip` over the
  tunnel on SSH port 22 - already allowed by the firewall baseline).
