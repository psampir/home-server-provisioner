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
| `fail2ban_trusted_networks` | `[]` | Extra networks appended to `fail2ban_ignoreip` |
| `fail2ban_ssh_port` | `ssh` | Port name from `/etc/services`, or a number |

## Notes

- The role uses the systemd backend, which matches the journal-based
  Debian 13 defaults. It does not parse `/var/log/auth.log` directly.
- Add management or monitoring addresses to `fail2ban_ignoreip`, or whole
  networks to `fail2ban_trusted_networks`, if they perform automated SSH
  checks or if a ban could lock out your own access path.
- `firewall` runs after `fail2ban` in `site.yml`. Both must be active for a
  ban to be effective; fail2ban installs its own rules, but the host
  firewall must not allow a bypass path.
- To inspect current bans, run `fail2ban-client status sshd` on the host.

## Ban notifications

Set `fail2ban_notify_action: true` to install
`/etc/fail2ban/action.d/hsp-notify.conf` and add it to the `sshd` jail.
Every ban then sends one `hsp-notify` message with the address, jail and
failure count; unbans stay silent.

| Variable | Default | Description |
|---|---|---|
| `fail2ban_notify_action` | `false` | Install and wire the action |
| `fail2ban_notify_bin` | `hsp-notify` path | Binary the action calls |
| `fail2ban_notify_priority` | `low` | ntfy priority of the message |
| `fail2ban_notify_tags` | `shield` | ntfy tags of the message |

Off by default because it needs the `notifications` role to provide the
binary, and a jail that references a missing action fails to start.
