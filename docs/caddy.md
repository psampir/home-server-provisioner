# Caddy

Caddy terminates TLS and reverse-proxies the services you self-host. The
toolkit supports two deployment modes, and they can coexist in one
environment.

## Choosing a mode

| | Stack-based ingress | Native hub role |
|---|---|---|
| Runs on | An app server, next to the workloads | The `vpn_server` hub |
| Managed by | `compose_deploy` | The `caddy` role |
| Source on controller | `configs/<ENV>/stacks/<host>/caddy/` | `configs/<ENV>/caddy/` |
| Service | Docker container | Native `systemd` service |
| Ports | Published by Docker | Opened in UFW by the role |
| CA and data | A bind mount, usually under `/srv/data` | `/var/lib/caddy/` |
| Backends | Container names on a shared Docker network | `10.10.0.x` addresses over WireGuard |
| Best for | Workloads that should stay close to their data | A public ingress on a VPS, or a hub-only setup |

The sample deployment uses the stack-based mode: Caddy runs on the app
server and the WireGuard hub runs only `wireguard` and `dnsmasq`. The native
role remains available for environments that want Caddy on the hub, and
`playbooks/site.yml` still applies it to `vpn_server` when
`configs/<ENV>/caddy/` exists.

Do not enable both modes for the same hostnames. Pick one ingress owner per
environment.

## Stack-based ingress

### Layout

```
configs/<ENV>/stacks/<host>/caddy/
├── compose.yaml
└── Caddyfile
```

`compose_deploy` syncs the directory to `/opt/stacks/caddy/` on the host and
runs Compose. The Caddyfile is mounted read-only into the container.

### Compose file

```yaml
services:
  caddy:
    container_name: caddy
    image: caddy:2.9.1
    restart: unless-stopped
    ports:
      - "80:80"
      - "443:443"
      - "443:443/udp"
    volumes:
      - ./Caddyfile:/etc/caddy/Caddyfile:ro
      - /srv/data/docker-apps-data/caddy-data/caddy_data:/data
      - /srv/data/docker-apps-data/caddy-data/caddy_config:/config
    networks:
      - reverse_proxy

networks:
  reverse_proxy:
    external: true
```

Pin a specific Caddy tag. The example uses `2.9.1`; update it deliberately
and run `make validate-stacks` after changing an image.

If the ingress should be reachable only over the VPN or LAN, bind the
published ports to one address instead of all interfaces:

```yaml
    ports:
      - "10.10.0.2:80:80"
      - "10.10.0.2:443:443"
      - "10.10.0.2:443:443/udp"
```

Use the app server's `vpn_ip` from the inventory. Binding to `0.0.0.0`
publishes the ports on every interface, including a public one if the host
has it.

### Shared network

The Caddy container and every backend it proxies must share a Docker
network. The convention in this project is an external network named
`reverse_proxy`, created by `compose_deploy` before the stacks start:

```yaml
compose_deploy_external_networks:
  - reverse_proxy
```

Each backend stack joins it:

```yaml
services:
  immich-server:
    image: ghcr.io/immich-app/immich-server:<digest>
    networks:
      - reverse_proxy

networks:
  reverse_proxy:
    external: true
```

Caddy then uses the backend's container name, not its host address:

```caddy
immich.gr15 {
    tls internal
    reverse_proxy immich_server:2283
}
```

If the name or port is wrong, Caddy starts but returns 502. Check the
backend's `container_name` and the port it listens on inside the container.

### Caddyfile

```caddy
{
    pki {
        ca internal
    }
}

immich.gr15 {
    tls {
        issuer internal {
            ca internal
        }
    }
    reverse_proxy immich_server:2283
}

joplin.gr15 {
    tls {
        issuer internal {
            ca internal
        }
    }
    reverse_proxy joplin:22300
}
```

The global `pki` block names the internal CA. Each site block uses that CA
explicitly, so a future public site can use ACME without changing the
internal sites.

### Internal CA

The stack stores CA data in `/data` inside the container. With the bind
mount above, the root certificate is also visible on the host at:

```
/srv/data/docker-apps-data/caddy-data/caddy_data/pki/authorities/local/root.crt
```

Read it through the container to avoid guessing the path:

```bash
docker exec caddy cat /data/pki/authorities/local/root.crt
```

Trust this certificate once on every client that should use the internal
names. On Linux:

```bash
sudo cp caddy-root.crt /usr/local/share/ca-certificates/caddy-root.crt
sudo update-ca-certificates
```

For browsers and phones, import the same file through the system or browser
certificate store.

### Firewall

Docker publishes container ports with its own rules, which bypass UFW. That
means the `caddy` role's UFW rules do not apply to this mode, and adding
80/443 to `firewall_allow_rules` does not close or open the container.

Control exposure with the `ports` binding:

- `10.10.0.2:443:443` exposes HTTPS only on the VPN address.
- `127.0.0.1:8080:80` exposes it only to processes on the host.
- `443:443` exposes it on every interface.

If the host has a public interface and you need a public site, publish 80
and 443 there deliberately and add a host firewall rule for the Docker
chain. See [roles/firewall/README.md](../roles/firewall/README.md#docker-bypasses-ufw).

### DNS

`dnsmasq` runs on the WireGuard hub. For a wildcard internal name:

```yaml
dnsmasq_extra_addresses:
  - { name: gr15, ip: 10.10.0.2 }
```

This answers every `*.gr15` query from VPN peers with the app server's VPN
address. The name does not need a per-host record.

LAN clients cannot use the hub resolver: the hub is a VPS, it is not on the
home LAN, and VPN clients are not routed to the LAN. If LAN clients should
reach the local Caddy, give them a LAN resolver that returns the app
server's LAN address, or add a local `/etc/hosts` entry. Do not add a LAN
address to `dnsmasq_extra_hosts` and expect VPN clients to reach it.

### Operations

```bash
# Validate the rendered config inside the running container
docker exec caddy caddy validate --config /etc/caddy/Caddyfile

# Reload after a config change
docker exec caddy caddy reload --config /etc/caddy/Caddyfile

# Follow logs
docker logs -f caddy

# Recreate the stack after changing compose.yaml
docker compose -f /opt/stacks/caddy/compose.yaml up -d
```

`compose_deploy` runs `docker compose up -d` for the stack. A Caddyfile
change alone needs a reload; a Compose change needs a recreate.

The complete stack example lives in the sample deployment tree under
`configs/<ENV>/stacks/<host>/caddy/` if you have a private config repo.

## Native hub role

Use this mode when Caddy should be the single public ingress on the
WireGuard hub, or when the hub is the only host with a stable public
address.

### Layout

```
configs/<ENV>/caddy/
├── Caddyfile               # main config (required)
└── conf.d/                 # optional snippets
    ├── public.caddy
    └── internal.caddy
```

The role mirrors the tree to `/etc/caddy/`. Pull snippets in with:

```caddy
import /etc/caddy/conf.d/*.caddy
```

Snippet order is undefined, so each `*.caddy` file must contain complete
site blocks, not fragments.

Every change runs `caddy validate` before the reload handler, so a typo
does not take existing sites down.

### Opting out

If `configs/<ENV>/caddy/` does not exist on the controller, the role is a
no-op: Caddy is not installed and no firewall ports are opened. This keeps
the role in `playbooks/site.yml` without affecting environments that use a
stack instead.

If the directory exists but has no `Caddyfile`, the role fails loudly.

### TLS modes

#### `tls internal`

```caddy
whoami.home {
    tls internal
    reverse_proxy 10.10.0.2:8080
}
```

Caddy mints certificates from its local CA. Trust the root once on each
client:

```bash
sudo cat /var/lib/caddy/.local/share/caddy/pki/authorities/local/root.crt
```

This is the right mode for names that resolve only through `dnsmasq` and
exist only inside the tunnel.

#### ACME HTTP-01

```caddy
{
    email admin@example.com
}

app.example.com {
    reverse_proxy 10.10.0.2:3000
}
```

Requires:

- A public A/AAAA record for the name pointing at the hub.
- Inbound 80/tcp reachable on the hub. The role opens it in UFW; a NAT
  router in front of the hub also needs a forward.
- `email` in the global block.

#### ACME DNS-01

```caddy
*.example.com {
    tls {
        dns cloudflare {env.CF_API_TOKEN}
    }
    reverse_proxy 10.10.0.2:3000
}
```

The Debian package ships the stock Caddy build. DNS-01 needs a provider
plugin, so use an `xcaddy` build or an official image with the plugin.

### Firewall

The role manages its own UFW rules. Do not add Caddy ports to
`firewall_allow_rules`.

| Port | Why | Variable |
|---|---|---|
| 80/tcp | HTTP and ACME HTTP-01 | `caddy_open_http` |
| 443/tcp | HTTPS | `caddy_open_https` |
| 443/udp | HTTP/3 (QUIC) | `caddy_open_http3` |

```yaml
caddy_open_firewall: true
caddy_firewall_from: [any]       # use 10.10.0.0/24 for VPN-only exposure
caddy_open_http: true
caddy_open_https: true
caddy_open_http3: true           # set false to leave 443/udp closed
```

For a VPN-only hub with no public sites:

```yaml
caddy_firewall_from:
  - 10.10.0.0/24
caddy_open_http: false
caddy_open_https: true
caddy_open_http3: false
```

### Operations

```bash
sudo caddy validate --config /etc/caddy/Caddyfile
sudo caddy adapt --config /etc/caddy/Caddyfile | jq .
sudo systemctl reload caddy
sudo systemctl restart caddy       # only when reload is not enough
journalctl -u caddy -f
```

## Site-block patterns

These work in both modes. Use container names in stack mode and
`10.10.0.x` addresses in native mode.

### One backend behind one hostname

```caddy
git.example.com {
    reverse_proxy 10.10.0.2:3000
}
```

### Multiple backends on different app servers

```caddy
git.example.com {
    reverse_proxy 10.10.0.2:3000
}

files.example.com {
    reverse_proxy 10.10.0.3:3923
}
```

### Split internal and public copies of one app

```caddy
git.example.com {
    reverse_proxy 10.10.0.2:3000
}

git.home {
    tls internal
    reverse_proxy 10.10.0.2:3000
}
```

Add `git.home` to DNS only if clients should resolve the internal name.
In stack mode this is a `dnsmasq_extra_addresses` wildcard or a per-host
record; in native mode it is `dnsmasq_extra_hosts`.

### Static file root

```caddy
files.home {
    tls internal
    root * /srv/files
    file_server browse
}
```

This serves files from the Caddy container or host filesystem, depending on
the mode. Mount the directory into the container if you use stack mode.

## LAN bandwidth

A hub-based ingress routes LAN traffic through the VPS. A laptop on the same
LAN as `app-1`, downloading a large file from `copyparty` on `app-1` via
`copyparty.example.com`, sends every byte through the hub and back.

For dashboards and configuration UIs this is invisible. For bulk transfers
it hurts. The stack-based mode avoids the detour because Caddy and the
backend are on the same LAN, and clients connect to the app server directly.

If you use the native hub role and bulk transfers matter, move ingress to a
stack on the app server instead of adding a second Caddy. Two ingress
owners for the same names is harder to reason about than one.

## Troubleshooting

### Validate without deploying

Stack mode:

```bash
docker exec caddy caddy validate --config /etc/caddy/Caddyfile
```

Native mode:

```bash
sudo caddy validate --config /etc/caddy/Caddyfile
```

### Follow logs

Stack mode:

```bash
docker logs -f caddy
```

Native mode:

```bash
journalctl -u caddy -f
sudo systemctl status caddy
```

### Browser warns about the certificate

This is expected with `tls internal`. Trust the root certificate once:

- Stack mode: `docker exec caddy cat /data/pki/authorities/local/root.crt`
- Native mode: `sudo cat /var/lib/caddy/.local/share/caddy/pki/authorities/local/root.crt`

Import the file into the system or browser trust store. A certificate
warning after trusting the root usually means the client is connecting to a
different name than the one in the certificate, or an old certificate is
cached.

### 502 Bad Gateway

Caddy reached the site block but could not reach the backend.

- Stack mode: the backend container must be on the same Docker network and
  the name in `reverse_proxy` must match its `container_name` or service
  alias. Check the port inside the container, not the published port.
- Native mode: the backend must be reachable at the `10.10.0.x` address
  over WireGuard. Check `ping` and `curl` from the hub.

### Reload did not pick up the change

Stack mode:

```bash
docker exec caddy caddy reload --config /etc/caddy/Caddyfile
```

Native mode:

```bash
sudo systemctl reload caddy
```

If validation failed, the file was not replaced. Check the playbook or
Compose output first. A full restart drops in-flight connections; use it
only when a reload is not enough.

### Port is open even though UFW says it is closed

This is the Docker bypass. Published container ports are handled by Docker's
own rules before UFW. Change the `ports` binding in `compose.yaml`, not
`firewall_allow_rules`. See
[roles/firewall/README.md](../roles/firewall/README.md#docker-bypasses-ufw).

### DNS resolves to the wrong address

Check from the client:

```bash
getent hosts immich.gr15
resolvectl query immich.gr15
```

VPN peers should receive the app server's `vpn_ip`. LAN clients should
receive the LAN address from a LAN resolver. The hub resolver is not
reachable from the LAN and VPN clients do not route to the LAN.

## Migrating from the native role to a stack

1. Create `configs/<ENV>/stacks/<host>/caddy/` with the Compose file and
   Caddyfile.
2. Move the site blocks from `configs/<ENV>/caddy/Caddyfile` into the stack
   Caddyfile. Replace `10.10.0.x` backends with container names where the
   backends share the `reverse_proxy` network.
3. Point DNS at the app server's `vpn_ip`.
4. Apply the stack with `compose_deploy`.
5. Trust the new internal CA root on clients.
6. Remove `configs/<ENV>/caddy/` and re-provision to make the native role a
   no-op, or disable the role for that environment.

Do not run both ingress modes against the same hostnames during the
transition. Move DNS last so clients switch in one step.
