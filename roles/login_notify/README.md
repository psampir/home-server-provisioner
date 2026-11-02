# login_notify

Reports every PAM session opening through `hsp-notify`, so an SSH login is
visible even when it does not fail. The hook is optional and fire and
forget: a broken backend never blocks or delays a login.

## What it does

1. Installs `/usr/local/bin/hsp-login-notify`.
2. Renders `/etc/hsp/login-notify.conf`.
3. Appends `session optional pam_exec.so quiet ...` to every service in
   `login_notify_pam_services` (sshd by default).

## Variables

| Variable | Default | Description |
|---|---|---|
| `login_notify_enabled` | `false` | Master switch; also removes the hook and files |
| `login_notify_ignore_users` | `[ansible]` | Accounts that never notify |
| `login_notify_trusted_nets` | `[]` | CIDRs that count as trusted |
| `login_notify_trusted_priority` | `low` | ntfy priority for trusted logins |
| `login_notify_untrusted_priority` | `high` | ntfy priority for everything else |
| `login_notify_pam_services` | `[sshd]` | Files under `/etc/pam.d` to hook |

Logins from a trusted network use the plain `login` tag. Anything else,
including a public address, adds `rotating_light` and the high priority.
An empty `PAM_RHOST` is treated as the local console.

## Notes

- The PAM line is `optional`, and the script exits 0, so a missing binary
  or a failing backend cannot lock anyone out.
- The notification runs under `nohup` in the background. `hsp-notify`
  retries a failing backend, and that must never delay the session.
- The role checks for `pam_exec.so` before touching PAM.
- `PAM_TYPE=close_session` is ignored; only `open_session` notifies.
