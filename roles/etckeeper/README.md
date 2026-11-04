# etckeeper

Keeps `/etc` in a local git repository. The package installs an apt hook
that commits before and after every package operation, so a config
migration is visible as a diff instead of being silently overwritten.

## What it does

1. Installs `etckeeper` and uses git as the VCS.
2. Initializes `/etc/.git` if the package did not do it already.
3. Sets a local git identity so apt can commit without a global config.
4. Creates the initial commit when the repository has no history.

## What it gives you

- `etckeeper vcs log` shows the apt-related commits.
- `etckeeper vcs show --stat HEAD` shows which `/etc` files changed.
- `etckeeper vcs diff <commit> -- <file>` shows the exact change.
- A single file can be restored with `etckeeper vcs checkout <commit> -- <file>`.

## Variables

| Variable | Default | Description |
|---|---|---|
| `etckeeper_commit_name` | `etckeeper` | Git author name for automatic commits |
| `etckeeper_commit_email` | `etckeeper@<host>` | Git author email |

## Security

The repository lives in `/etc/.git` and is readable by root only. It
contains `/etc` secrets (WireGuard keys, SSH host keys, notification
tokens). Do not add a remote and do not push it anywhere. It is a local
history for migration and rollback, not a backup.
