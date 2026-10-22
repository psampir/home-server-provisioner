# Networking

How the fleet is wired: a single WireGuard hub, a DNS resolver that rides
the same tunnel, and one public inbound port for the VPN. Individual hosts
may still expose services on their own LAN or VPN address.

## Topology: one hub, dial-out spokes

The model is **hub-and-spoke**. Exactly one host is the hub:

```yaml
# configs/<ENV>/inventory/host_vars/<hub>.yml
wireguard_role: hub
vpn_ip: 10.10.0.1
```

It is also the only member of the `vpn_server` group. The `wireguard`
role asserts that exactly one host declares `wireguard_role: hub`, and
`wireguard_hub_host` is derived from that single `vpn_server` entry:

```yaml
wireguard_hub_host: "{{ (groups['vpn_server'] | default([]))[0] | default('') }}"
```

Every other server runs the role with the default `wireguard_role: peer`
and gets exactly one `[Peer]` section - the hub.

### Peers dial out, so peers need no inbound ports

Both managed peers (`wg0.peer.conf.j2`) and external clients
(`client.conf.j2`) contain an `Endpoint` pointing at the hub:

```jinja
wireguard_hub_endpoint: "{{ hostvars[wireguard_hub_host].ansible_host }}:{{ wireguard_listen_port }}"
```

That is simply the hub's inventory `ansible_host` plus the listen port
(`51820` by default). In the Incus lab that is the hub VM's LAN address;
in production it must be the address clients can actually reach - the
VPS's public IP or a DNS name that resolves to it.

Consequences:

- **Only the hub needs a public inbound port** for WireGuard (UDP 51820).
  Peers and client devices open an outbound UDP socket and keep the mapping
  alive with `PersistentKeepalive = 25`. Other services, such as Caddy on
  an app server, are separate listeners on the LAN or VPN address.
- A peer behind NAT, CGNAT, or a mobile network works without any port
  forwarding, and its address can change freely.
- If a peer is unreachable, the fix is on the hub/endpoint side, not a
  firewall rule on the peer.

The hub also enables IP forwarding and (by default) masquerades
`wireguard_subnet` out of its WAN interface, so peers can reach each
other through the hub and full-tunnel clients can reach the internet.
`wireguard_wan_interface` is auto-detected from the hub's default route.

## Address plan (`vpn_ip`)

`wireguard_subnet` defaults to `10.10.0.0/24`; `wireguard_hub_ip` is
`10.10.0.1`. Every managed server needs a `vpn_ip` in `host_vars`;
external clients declare theirs in `wireguard_clients`.

| Range | Use |
| --- | --- |
| `.1` | Hub |
| `.2` - `.19` | Managed peers (servers in the inventory) |
| `.20` - `.254` | External clients (phones, laptops) |

The split is a convention, not something the code enforces - the role
only asserts that every address is inside `wireguard_subnet` and unique
across managed hosts and clients. Keeping it lets you tell a server from
a phone at a glance, and leaves the low range free for adding servers
later without renumbering clients.

Avoid choosing a VPN subnet that collides with the LAN or with Docker's
default bridges (`172.17.0.0/16`, `172.18.0.0/16`). The Incus test env
puts its isolated DHCP lab LAN on `192.168.50.0/24` (see
`scripts/test-env.sh`), so that range is worth avoiding too.

## DNS: who owns `/etc/resolv.conf`

There are three DNS roles in play, and only one of them may own
`/etc/resolv.conf` on a given host.

### The hub runs dnsmasq

The `dnsmasq` role (applied to `vpn_server`) stops and masks
`systemd-resolved` to free port 53, then writes `/etc/resolv.conf`
pointing at `127.0.0.1` with `dnsmasq_resolv_fallback` (`1.1.1.1` by
default) as a safety net.

dnsmasq listens on `dnsmasq_interfaces` - `lo` and `wg0` by default - and
uses `bind-dynamic` so `wg0` may appear after dnsmasq starts. It serves
`dnsmasq_domain` (`home` by default), auto-generates a `host-record` for
every host in `dnsmasq_inventory_groups` (`servers`) using that host's
`vpn_ip` when defined and its `ansible_host` otherwise, and forwards
everything else to `dnsmasq_upstream_servers`. Because the records use
`vpn_ip`, a name always resolves to the tunnel address - traffic to a
peer stays inside WireGuard even when both machines share a LAN.

### App servers run `dns_client`

The `dns_client` role (applied to `app_servers`) also masks
`systemd-resolved`, removes the `/etc/resolv.conf` symlink it leaves
behind, and writes a static file:

```text
nameserver 10.10.0.1     # wireguard_hub_ip
nameserver 1.1.1.1       # fallback, dns_client_nameservers[1]
search home              # dns_client_search
```

So split-horizon resolution works with no per-host DNS configuration:
`hsp-app` asks the hub over the tunnel and gets `vpn_ip` answers back.

Before `dns_client` runs, the earlier `base` role seeds a temporary
`nameserver` when a fresh host has none, so the first apt call can reach the
network. On hosts with `/etc/dhcpcd.conf` both roles also add
`nohook resolv.conf`, otherwise dhcpcd would overwrite the static file on
the next lease renewal. See [roles/base/README.md](../roles/base/README.md)
and [roles/dns_client/README.md](../roles/dns_client/README.md).

### Backup targets get neither

Hosts that are only in `backup_targets` run `borg_repo` and not
`dns_client`. They do not need the hub's resolver: borgmatic pushes to
the target's `vpn_ip`, and the target answers on that address. This is
deliberate - see the next section.

### Why wg-quick must not manage peer DNS

`wg-quick` can write a `DNS =` line and install resolvconf hooks. On
managed peers that is **off** by default (`wireguard_peer_manage_dns:
false`), and it must stay off on any host where `dns_client` owns
`/etc/resolv.conf`.

The failure mode is subtle, because the *first* provision succeeds:

1. The peer template emits `DNS = 10.10.0.1`, so `wg-quick` asks
   `resolvconf` to program `systemd-resolved`.
2. `systemd-resolved` is masked on that host, so the call fails with
   `Unit dbus-org.freedesktop.resolve1.service failed to load properly`.
3. `wg-quick` treats a failed `PostUp`/resolvconf step as fatal and
   tears the interface down again.

The interface comes up on a fresh boot only because there is no config
change to trigger a restart; the **second** `make provision` restarts
`wg-quick@wg0`, and the tunnel dies. Keeping DNS management off - and
letting `dns_client` write a static file - is what makes re-provisioning
idempotent.

External clients are different: `client.conf.j2` always emits
`DNS = {{ wireguard_client_dns }}` and has no `resolvectl` hooks. That sends
all client DNS queries to the hub resolver, which forwards them upstream.
It is full DNS through the hub, not split DNS. For split DNS, add a
domain-scoped setting such as `~home` to the client configuration, or
configure split DNS in the operating system. The template does not do that
by default.

## Local records beyond the inventory

Two variables extend what dnsmasq answers:

- `dnsmasq_extra_hosts` - static `host-record` entries. A name without a
  dot gets `dnsmasq_domain` appended; a name containing a dot is used
  verbatim as an FQDN.

  ```yaml
  dnsmasq_extra_hosts:
    - { name: nas, ip: 10.10.0.5 }               # → nas.home
    - { name: files.example.lan, ip: 10.10.0.2 } # → files.example.lan
  ```

  Use addresses that VPN peers can reach. The hub does not route to the
  home LAN, so a `192.168.x.x` record would resolve but the connection would
  fail. For LAN-only names, use a LAN resolver instead.

- `dnsmasq_extra_addresses` - `address=` entries, rendered **before** the
  upstream forwarders so they win the priority race. Use these to answer
  for names under a domain that is otherwise forwarded upstream (for
  example a Caddy site that the upstream DNS knows nothing about).

  ```yaml
  dnsmasq_extra_addresses:
    - { name: files.example.lan, ip: 10.10.0.1 }
  ```

`address=` also accepts a **bare domain**, which makes dnsmasq answer for
that name and everything beneath it. Pointing an internal TLD at a server
is a one-liner:

```yaml
dnsmasq_extra_addresses:
  - { name: gr15, ip: 10.10.0.2 }   # renders: address=/gr15/10.10.0.2
```

That resolves `gr15` and every `*.gr15` name to `10.10.0.2`; Caddy on
that host then dispatches by `Host` header. No wildcard syntax is needed.

## Firewall interaction

UFW is the host firewall on every server, configured by the `firewall`
role:

- Default **incoming deny**, **outgoing allow**.
- SSH (`firewall_ssh_port`, 22) is always allowed as lockout protection.
- `firewall_allow_rules` adds anything else, and is fully reconciling:
  rules removed from the list are deleted on the next run, tracked in a
  per-host manifest.

Other roles open the ports they need directly and are intentionally
*not* part of that manifest, so they are never pruned by it:

| Role | Opens |
| --- | --- |
| `firewall` | 22/tcp (always), plus `firewall_allow_rules` |
| `wireguard` | 51820/udp from `wireguard_firewall_from` (hub only) |
| `dnsmasq` | 53/tcp + 53/udp from `dnsmasq_firewall_from`; 67/udp when DHCPv4 is enabled, and 547/udp only for `dhcpv6` or `both` |
| `caddy` | Native role only: 80/tcp (ACME), 443/tcp, and 443/udp (HTTP/3) when a Caddyfile exists. A Caddy Compose stack publishes ports through Docker and bypasses UFW. |

Both `wireguard_firewall_from` and `dnsmasq_firewall_from` default to
`any`. dnsmasq can afford that because `bind-dynamic` only listens on
`dnsmasq_interfaces`; scoping to private CIDRs is optional
defence-in-depth.

### Docker is the exception

UFW protects the INPUT chain. Docker inserts its own iptables/nftables
rules that are evaluated *before* UFW, and a container port published
with `ports:` is NATed to the container regardless of UFW. A
`ufw deny 8080` will not stop a container that publishes `8080:8080`.

Bind published ports to a tunnel/LAN address or `127.0.0.1` instead of
`0.0.0.0`, put a reverse proxy in front, or filter in `DOCKER-USER`. See
[Docker bypasses UFW](../roles/firewall/README.md#docker-bypasses-ufw)
for the full explanation and workarounds. The `firewall` role does not
manage `DOCKER-USER`.

## Naming: `home` vs `home.arpa`

`dnsmasq_domain` defaults to `home`, which is fine inside a lab. For
anything reachable from outside a lab - a VPN client on a public Wi-Fi
network, a host at a friend's house, a mobile phone - prefer
`home.arpa`. It is reserved for exactly this purpose by
[RFC 8375](https://www.rfc-editor.org/rfc/rfc8375) and will never resolve
on the public internet, which avoids leaking queries and avoids
collisions with real TLDs. `.local` should be avoided entirely: it is
reserved for mDNS and will misbehave on macOS and Linux desktops.

If you change `dnsmasq_domain`, update `dns_client_search` to match.

## Related reading

- [`docs/wireguard-clients.md`](wireguard-clients.md) - onboarding
  phones and laptops, split vs full tunnel, key management
- [`roles/dnsmasq/README.md`](../roles/dnsmasq/README.md) - full DNS and
  optional DHCP/RA reference
- [`roles/wireguard/README.md`](../roles/wireguard/README.md) - role
  reference and the test-environment regression check
- [`roles/firewall/README.md`](../roles/firewall/README.md) - UFW
  reconciliation and the Docker bypass
