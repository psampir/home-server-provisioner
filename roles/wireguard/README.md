# wireguard

Hub-and-spoke WireGuard for the fleet. Exactly one host is the **hub**
(`wireguard_role: hub`, usually the public VPS); every other host running
the role is a **managed peer** with a single `[Peer]` section pointing at
the hub. Phones/laptops are not managed hosts - they are declared in
`wireguard_clients` and appear only as `[Peer]` sections on the hub.

## What it does

- Installs `wireguard` + `wireguard-tools`.
- Generates the host's private key in place (`/etc/wireguard/wg0.privkey`,
  never leaves the host) and derives/persists its public key.
- Renders `/etc/wireguard/wg0.conf`:
  - hub → `templates/wg0.hub.conf.j2` (all managed peers + external
    clients, optional NAT);
  - peer → `templates/wg0.peer.conf.j2` (single `[Peer]` = hub).
- Enables `wg-quick@wg0` and restarts it when the config changes.
- On the hub only: enables IP forwarding, optional NAT/masquerade, opens
  UDP 51820 and allows peer-to-peer forwarding.

Client `.conf` + QR artifacts are deliberately **not** written during
`make provision`; use `make wireguard-render` (see `docs/wireguard-clients.md`).

## Variables

See `defaults/main.yml` for the full list.

| Variable | Default | Purpose |
| --- | --- | --- |
| `wireguard_role` | `peer` | `hub` on exactly one host |
| `wireguard_subnet` | `10.10.0.0/24` | VPN CIDR |
| `wireguard_hub_ip` | `10.10.0.1` | Hub address inside the VPN |
| `wireguard_subnet_prefix` | `24` | Prefix length written after each `Address` |
| `wireguard_client_dns` | `wireguard_hub_ip` | DNS forced into **external client** configs |
| `wireguard_client_dns_search` | `[]` | Domains appended to the client DNS line; `~domain` enables split DNS with wg-quick |
| `wireguard_peer_manage_dns` | `false` | Whether wg-quick manages DNS on **server peers** |
| `wireguard_peer_dns` | `wireguard_hub_ip` | DNS server written to peer configs when the above is true |
| `wireguard_hub_domain` | `""` | Split-DNS search domain for the hub (peer configs only) |

Per-host: `vpn_ip` is required (`.2`-`.19` by convention).
Per-client `dns` and `dns_search` entries override the global client DNS
values.

External client configs render:

```ini
DNS = {{ wireguard_client_dns }}{% if wireguard_client_dns_search %}, {{ wireguard_client_dns_search | join(', ') }}{% endif %}
```

Set `wireguard_client_dns_search: ["~gr15"]` for split DNS on wg-quick.
The `~` prefix is platform-specific; see
[docs/wireguard-clients.md](../../docs/wireguard-clients.md#dns).

The Android app rejects `~gr15` in `DNS` with `Cannot parse IP address`.
Set a per-client `dns_search: []` for Android (and any app that rejects the
line); those clients then use the hub resolver for all names.

## DNS on managed peers

`wireguard_peer_manage_dns` controls whether the peer template emits a
`DNS` line and the split-DNS hooks:

```ini
DNS     = <wireguard_peer_dns>
PostUp  = resolvectl domain wg0 "~<wireguard_hub_domain>"
PreDown = resolvectl domain wg0 ""
```

**It defaults to `false` and should normally stay that way.** Server peers
do not need wg-quick to touch DNS:

- Hosts in `app_servers` run the `dns_client` role, which masks
  `systemd-resolved` and writes `/etc/resolv.conf` itself. `wg-quick`'s
  `resolvconf -a wg0` then fails with
  `Unit dbus-org.freedesktop.resolve1.service failed to load properly`,
  and `wg-quick` tears the interface down again.
- Backup targets do not need the hub's resolver at all - they reach other
  peers by their `vpn_ip`.

The failure is a **re-provision regression**: the first provision writes
the config and brings the interface up, but the second run restarts
`wg-quick@wg0` and it dies on the DNS setup step. Leaving this off is what
makes `make provision` idempotent on `dns_client` hosts.

`wireguard_hub_domain` only has an effect when
`wireguard_peer_manage_dns: true`: the `resolvectl` hooks require a live
`systemd-resolved`, which `dns_client` hosts do not have. Setting it alone
is a no-op - and that is the correct state on hosts where `dns_client`
owns DNS.

External clients are unaffected: `client.conf.j2` always emits
`DNS = {{ wireguard_client_dns }}` and has no `resolvectl` hooks.

## Test environment

`configs/test/inventory` is the Incus lab (`hsp-vpn` hub,
`hsp-app`/`hsp-app2` app servers with `dns_client`,
`hsp-backup`/`hsp-backup2`). A second `make provision` there is the
regression check for the DNS issue above.
