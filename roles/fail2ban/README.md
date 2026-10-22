# fail2ban

Installs fail2ban and enables an SSH jail backed by the systemd journal.

## What it does

1. Installs `fail2ban`.
2. Writes `/etc/fail2ban/jail.local` with global ban, find and retry
   settings, the `ignoreip` list, and `backend = systemd`.
3. Writes `/etc/fail2ban/jail.d/sshd.local` with the `sshd` jail.
4. Enables and starts `fail2ban`.

## Variables

| Variable | Default | Description |
|---|---|---|
| `fail2ban_bantime` | `1h` | How long an address stays banned |
| `fail2ban_findtime` | `10m` | Window used to count failed attempts |
| `fail2ban_maxretry` | `5` | Failed attempts before a ban |
| `fail2ban_ignoreip` | `127.0.0.1/8`, `::1` | Addresses that are never banned |
| `fail2ban_ssh_port` | `ssh` | Port name from `/etc/services`, or a number |

## Notes

- The role uses the systemd backend, which matches the journal-based
  Debian 13 defaults. It does not parse `/var/log/auth.log` directly.
- Add management or monitoring addresses to `fail2ban_ignoreip` if they
  perform automated SSH checks.
- `firewall` runs after `fail2ban` in `site.yml`. Both must be active for a
  ban to be effective; fail2ban installs its own rules, but the host
  firewall must not allow a bypass path.
- To inspect current bans, run `fail2ban-client status sshd` on the host.
