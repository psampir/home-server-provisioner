# dns_client

Points `/etc/resolv.conf` on app servers at the WireGuard hub (which runs
`dnsmasq` for the `home` domain), with a public resolver as fallback.

## What it does

1. Stops and masks `systemd-resolved` (configurable via
   `dns_client_disable_resolved`).
2. Removes the `/etc/resolv.conf` symlink that systemd-resolved leaves
   behind.
3. If `/etc/dhcpcd.conf` exists, adds `nohook resolv.conf` before the first
   `interface`, `ssid` or `profile` block. Without it, dhcpcd rewrites
   `/etc/resolv.conf` on the next lease renewal and silently discards the
   static file.
4. Writes the static resolver file.

`roles/base` performs the same dhcpcd change earlier so that its first apt
call has working DNS. Both steps are idempotent, so the role is safe to run
on hosts that `base` already prepared.

## Variables

| Variable | Default | Description |
|---|---|---|
| `dns_client_nameservers` | hub IP, `1.1.1.1` | Resolvers written to `/etc/resolv.conf` |
| `dns_client_search` | `home` | Search domain |
| `dns_client_disable_resolved` | `true` | Stop and mask systemd-resolved |

## Notes

- Keep `wireguard_peer_manage_dns: false` on any host where this role owns
  `/etc/resolv.conf`. See [docs/networking.md](../../docs/networking.md).
- This role runs only in the `app_servers` play, after `base`.
