# dnsmasq

Local DNS for the fleet, with an **optional** DHCP + IPv6 Router
Advertisement server for hosts that should act as the LAN's network
authority (Pi-hole-style).

## What it does

- Installs dnsmasq and disables `systemd-resolved` so dnsmasq can own
  port 53, then points `/etc/resolv.conf` at it (with a fallback resolver).
- Serves a local domain (`dnsmasq_domain`, default `home`) and auto-generates
  `host-record` entries from the Ansible inventory (every host in
  `dnsmasq_inventory_groups`, using `vpn_ip` when present, else
  `ansible_host`). Extra static records via `dnsmasq_extra_hosts`.
- Forwards everything else to `dnsmasq_upstream_servers`.
- Opens port 53 (tcp+udp) in UFW.
- **Optionally** (opt-in) runs a DHCPv4 + IPv6 RA/DHCPv6 server on one LAN
  interface, registering client names into the same local DNS.

By default the role is a **pure DNS server** - DHCP stays off until you
opt in.

## DNS configuration

See `defaults/main.yml`. Common knobs: `dnsmasq_domain`,
`dnsmasq_upstream_servers`, `dnsmasq_interfaces` (defaults to `lo` + `wg0`),
`dnsmasq_extra_hosts`, `dnsmasq_extra_addresses`, `dnsmasq_log_queries`.

`dnsmasq_extra_addresses` is the usual way to point a whole domain at one
host, for example `{ name: gr15, ip: 10.10.0.2 }` to answer every `*.gr15`
name with the app server's VPN address. Use addresses that VPN peers can
reach; the hub does not route to the home LAN.

## DHCP + IPv6 (opt-in)

Enable this only on a host that should be the **DHCP/RA authority for a
physical LAN segment** (e.g. your home server replacing the router's DHCP).

> ⚠️ **Only one DHCP server may exist per broadcast domain.** Most routers
> run DHCP out of the box. Before enabling this, **disable your router's
> DHCP server**, or you will get lease conflicts. The router keeps doing
> routing/NAT; this host just hands out addresses and names.

DHCP is a LAN service - `dnsmasq_dhcp_interface` must be a physical/bridged
interface, **never** the WireGuard interface (peers are statically
addressed).

```yaml
# host_vars/<lan-authority>.yml
dnsmasq_dhcp_enabled: true
dnsmasq_dhcp_interface: enp6s0          # the LAN NIC (static, see below)

dnsmasq_dhcp_v4:
  start: 192.168.50.50
  end: 192.168.50.200
  netmask: 255.255.255.0
  lease: 12h
# Leave gateway empty if THIS host is the gateway. If the ROUTER is the
# gateway (Pi-hole-style), point clients at it:
dnsmasq_dhcp_v4_gateway: 192.168.50.1

# IPv6: slaac (default) | dhcpv6 | both | off
dnsmasq_dhcp_v6_mode: slaac
dnsmasq_dhcp_v6_prefix: "fd50:abcd:1234::/64"   # a ULA /64 for the segment

# Optional fixed reservations (also added to DNS via `name`):
dnsmasq_dhcp_static_leases:
  - { mac: "aa:bb:cc:dd:ee:ff", ip: 192.168.50.10, name: printer }
```

IPv6 modes:

| Mode | Client gets its address via | Use when |
| --- | --- | --- |
| `slaac` | SLAAC (RA autonomous flag); DNS via stateless DHCPv6 | Default; matches most home setups |
| `dhcpv6` | Stateful DHCPv6 pool | You want the server to assign/track every v6 address |
| `both` | Either SLAAC or DHCPv6 | Mixed clients |
| `off` | - (IPv4 only) | No IPv6 on the segment |

The role opens UDP 67 (DHCPv4) and, for `dhcpv6`/`both`, UDP 547 (DHCPv6).
Router Advertisements are ICMPv6 and already permitted by UFW's default
IPv6 rules.

## Static server interface (per-host, NOT managed here)

The other half of "server static, client dynamic": the **DHCP host itself
needs a static address** on `dnsmasq_dhcp_interface`. This role does **not**
manage host IP addressing - that is intentionally a per-host step so the
role stays focused and portable. Configure it once on the box, e.g. with
systemd-networkd:

```ini
# /etc/systemd/network/10-lan.network   (on the DHCP-authority host)
[Match]
Name=enp6s0

[Network]
Address=192.168.50.1/24
Address=fd50:abcd:1234::1/64
IPForward=ipv6          # needed if this host also routes for the segment
```

```bash
systemctl enable --now systemd-networkd
```

(Or the Debian `/etc/network/interfaces` equivalent, or your cloud/Incus
network profile.) The interface name and the addresses must match
`dnsmasq_dhcp_interface` and the chosen v4/v6 ranges.

## Test environment

`make test-env-create` provisions an isolated, DHCP-less "lab LAN" bridge
plus an `hsp-client` VM so the DHCP/SLAAC path can be exercised end-to-end
without colliding with Incus's own bridge DHCP. See `docs/networking.md`
and `scripts/test-env.sh`.
