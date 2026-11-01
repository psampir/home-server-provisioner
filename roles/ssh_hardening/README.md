# ssh_hardening

Hardens `sshd` on every managed host. Root login and password
authentication are disabled by default, and the less common authentication
paths are closed as well.

## What it does

Edits `/etc/ssh/sshd_config` in place, validating the result with
`sshd -t -f` before the handler restarts `ssh`:

1. Sets the listening ports in `/etc/ssh/sshd_config.d/00-hsp-ports.conf`.
   Two ports can be listed to migrate without losing access.
2. Disables root login.
3. Disables password authentication.
4. Disables keyboard-interactive challenge-response.
5. Sets `UsePAM`.
6. Limits `MaxAuthTries` and `LoginGraceTime`.
7. Disables empty passwords and X11 forwarding.
8. Optionally restricts logins to a list of accounts with `AllowUsers`.

## Variables

| Variable | Default | Description |
|---|---|---|
| `ssh_hardening_ports` | `[22]` | Listening ports, rendered into a drop-in |
| `ssh_hardening_permit_root_login` | `no` | `PermitRootLogin` value |
| `ssh_hardening_password_authentication` | `no` | `PasswordAuthentication` value |
| `ssh_hardening_challenge_response_authentication` | `no` | `KbdInteractiveAuthentication` value |
| `ssh_hardening_use_pam` | `yes` | `UsePAM` value |
| `ssh_hardening_max_auth_tries` | `3` | `MaxAuthTries` value |
| `ssh_hardening_login_grace_time` | `30` | `LoginGraceTime` in seconds |
| `ssh_hardening_permit_empty_passwords` | `no` | `PermitEmptyPasswords` value |
| `ssh_hardening_x11_forwarding` | `no` | `X11Forwarding` value |
| `ssh_hardening_allow_users` | `[]` | Accounts allowed to log in; empty keeps sshd's default |

## Notes

- Apply this role only after the admin and service keys are installed and
  tested. A configuration that disables passwords before key auth works can
  lock you out.
- Keep console or out-of-band access available while changing the defaults.
- `sshd -t` validation runs before the file is replaced, so a syntax error
  cannot take SSH down.
- The role edits the main `sshd_config`. A `Match` block later in the file
  can still override these values for specific users or networks.
- `AllowUsers` is the first match wins: a drop-in under
  `/etc/ssh/sshd_config.d/` that sets it is read before the main file and
  wins. Check with `sshd -T | grep -i allowusers` after the run.
- List every remote account that logs in, including service accounts used
  by backup pulls, so a narrow allow list does not break them.
- Ports live in a drop-in rather than the main file, so a migration can
  list the old and the new port at once. `Port` is additive: once any
  `Port` line exists, sshd no longer falls back to 22, so the list must
  always name every port you want open.
- Changing the port also means updating `firewall_ssh_port`,
  `fail2ban_ssh_port`, `ansible_port` and any external port monitor.
