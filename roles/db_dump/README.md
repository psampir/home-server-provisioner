# db_dump

Creates consistent dumps of containerised databases before a backup. The
role installs `/usr/local/bin/hsp-db-dump` and renders a JSON configuration
from variables in `host_vars`. It is inert until `db_dump_enabled` is true.

The tool is deliberately read-only towards the services: it uses
`docker exec` for PostgreSQL and MySQL/MariaDB, and the SQLite online backup
API for SQLite files. It never stops or restarts a container.

## What it does

- PostgreSQL: `pg_dump` (custom or plain) or `pg_dumpall`, with daily,
  weekly and monthly copies.
- MySQL/MariaDB: `mysqldump` or `mariadb-dump` with
  `--single-transaction`, `--quick`, `--routines`, `--events` and
  `--triggers`, with the same retention.
- SQLite: online backup with `PRAGMA integrity_check`, for one exact path
  or a glob of files. Glob labels come from the parent directory or the
  file stem.
- Freshness: checks that an application-managed dump is newer than a
  configured number of hours. It does not create that dump.
- Every dump is written to a temporary file, fsynced, and renamed into
  place. Modes are `0600` for files and `0700` for directories.
- A `flock` lock prevents a manual run and a borgmatic run from overlapping.
- All entries are attempted; the script exits non-zero if any of them fails,
  so a `before_everything` hook aborts the archive.

## Configuration

```yaml
db_dump_enabled: true

db_dump_postgres:
  - name: joplin
    container: joplin-db
    user: joplin
    database: joplin
    password_env: POSTGRES_PASSWORD
    format: custom
    output: /srv/data/docker-apps-data/joplin/backups
    retention:
      daily: 14
      weekly: 8
      monthly: 12

db_dump_mysql:
  - name: app
    container: app-db
    user: app
    password_env: MYSQL_PASSWORD
    database: app
    binary: mysqldump
    output: /srv/data/backups/mysql/app
    retention:
      daily: 14
      weekly: 8
      monthly: 12

db_dump_sqlite:
  - name: directus
    path: /srv/data/docker-apps-data/directus-db/data.db
    output: /srv/data/backups/sqlite/directus
    keep: 14

  - name: copyparty
    glob: /srv/data/docker-apps-data/copyparty/db/*/up2k.db
    label_from: parent
    output: /srv/data/backups/sqlite/copyparty
    keep: 14

db_dump_freshness:
  - name: immich
    glob: /srv/data/docker-apps-data/immich-data/backups/immich-db-backup-*.sql.gz
    max_age_hours: 26
```

### PostgreSQL fields

| Field | Default | Description |
|---|---|---|
| `name` | required | Unique name, used in filenames |
| `container` | required unless `command` | Docker container running PostgreSQL |
| `user` / `user_env` | one required | User name, or an env variable inside the container |
| `database` / `database_env` | one required unless `format: dumpall` | Database name, or an env variable |
| `password_env` | optional | Env variable inside the container, exported as `PGPASSWORD` |
| `format` | `custom` | `custom` (`-Fc`, `.dump`), `plain` (`-Fp`, `.sql`) or `dumpall` (`.sql`) |
| `output` | required | Base directory; dumps go to `daily/`, `weekly/`, `monthly/` |
| `retention` | `14/8/12` | Copies kept per period; `weekly`/`monthly` may be `0` to disable |
| `extra_args` | `[]` | Extra `pg_dump`/`pg_dumpall` arguments |
| `timeout` | `3600` | Seconds per dump |
| `command` | optional | Full argv override; stdout is the dump |

### MySQL/MariaDB fields

The same shape as PostgreSQL, with:

| Field | Default | Description |
|---|---|---|
| `binary` | `mysqldump` | `mysqldump` or `mariadb-dump` |
| `password_env` | `MYSQL_PASSWORD` | Exported as `MYSQL_PWD` inside the container |
| `all_databases` | `false` | Use `--all-databases` instead of one database |
| `database` / `database_env` | one required unless `all_databases` | Database name |

The password is only passed as an environment variable inside the
container, never on the command line.

### SQLite fields

| Field | Default | Description |
|---|---|---|
| `name` | required | Unique name, used in filenames |
| `path` / `glob` | exactly one | Exact file or an absolute glob |
| `output` | required | Directory that receives the backups |
| `keep` | `14` | Copies kept per source |
| `integrity_check` | `true` | Run `PRAGMA integrity_check` after the backup |
| `timeout` | `60` | SQLite connection timeout in seconds |
| `label_from` | `parent` | For globs: `parent`, `stem` or `none` |

### Freshness fields

| Field | Default | Description |
|---|---|---|
| `name` | required | Unique name |
| `glob` | required | Absolute pattern of application dumps |
| `max_age_hours` | required | Fail when the newest match is older |

## borgmatic integration

```yaml
borgmatic_source_directories:
  - /srv/data
  - /srv/backups

borgmatic_before_everything_commands:
  - /usr/local/bin/hsp-db-dump
```

The output directories must be in `borgmatic_source_directories`, so the
fresh dumps join the archive. Exclude the live database files (the
PostgreSQL data directories and the SQLite files with their `-wal` and
`-shm` sidecars); otherwise Borg archives inconsistent live files.

Use `before_everything`, not `before_backup`: the dump should run once per
borgmatic invocation, not once per repository.

## Manual runs

```bash
sudo hsp-db-dump --config /etc/hsp/db-dump.json
sudo hsp-db-dump --dry-run --verbose
```

`--dry-run` validates the configuration and lists what would be written,
without touching any file. The default configuration path is
`/etc/hsp/db-dump.json`; `HSP_DB_DUMP_CONFIG` overrides it.

## Variables

| Variable | Default | Description |
|---|---|---|
| `db_dump_enabled` | `false` | Install and render the configuration |
| `db_dump_bin` | `/usr/local/bin/hsp-db-dump` | Script path |
| `db_dump_config` | `/etc/hsp/db-dump.json` | Rendered configuration |
| `db_dump_docker_bin` | `docker` | Docker CLI name |
| `db_dump_lock_file` | `/run/hsp-db-dump.lock` | Lock file |
| `db_dump_postgres` | `[]` | PostgreSQL entries |
| `db_dump_mysql` | `[]` | MySQL/MariaDB entries |
| `db_dump_sqlite` | `[]` | SQLite entries |
| `db_dump_freshness` | `[]` | Freshness checks |

## Notes

- Run it as root, either from the borgmatic systemd service or with sudo.
  The containers are reached through the Docker socket.
- The script does not create the application dump checked by
  `db_dump_freshness`; configure the application to write one.
- The JSON file is generated from these variables. Edit `host_vars`, not
  `/etc/hsp/db-dump.json`; a provisioning run overwrites the file.
- The script is stdlib-only Python 3 and has no runtime dependencies.
