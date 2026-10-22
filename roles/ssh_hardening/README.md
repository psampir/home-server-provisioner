# ssh_hardening

Hardens `sshd` on every managed host. Root login and password
authentication are disabled by default, and the less common authentication
paths are closed as well.

## What it does

Edits `/etc/ssh/sshd_config` in place, validating the result with
`sshd -t -f` before the handler restarts `ssh`:

1. Disables root login.
2. Disables password authentication.
3. Disables keyboard-interactive challenge-response.
4. Sets `UsePAM`.
5. Limits `MaxAuthTries` and `LoginGraceTime`.
6. Disables empty passwords and X11 forwarding.

## Variables

| Variable | Default | Description |
|---|---|---|
| `ssh_hardening_permit_root_login` | `no` | `PermitRootLogin` value |
| `ssh_hardening_password_authentication` | `no` | `PasswordAuthentication` value |
| `ssh_hardening_challenge_response_authentication` | `no` | `KbdInteractiveAuthentication` value |
| `ssh_hardening_use_pam` | `yes` | `UsePAM` value |
| `ssh_hardening_max_auth_tries` | `3` | `MaxAuthTries` value |
| `ssh_hardening_login_grace_time` | `30` | `LoginGraceTime` in seconds |
| `ssh_hardening_permit_empty_passwords` | `no` | `PermitEmptyPasswords` value |
| `ssh_hardening_x11_forwarding` | `no` | `X11Forwarding` value |

## Notes

- Apply this role only after the admin and service keys are installed and
  tested. A configuration that disables passwords before key auth works can
  lock you out.
- Keep console or out-of-band access available while changing the defaults.
- `sshd -t` validation runs before the file is replaced, so a syntax error
  cannot take SSH down.
- The role edits the main `sshd_config`. A `Match` block later in the file
  can still override these values for specific users or networks.
