# Caddy

Reverse proxy for everything you self-host. Runs natively on the WireGuard
hub (`vpn_server` group) and proxies traffic to backends across the
mesh through the existing WG tunnel.

## Why on the hub

The same machine that already terminates VPN traffic (`wireguard`) and
answers DNS (`dnsmasq`) is the natural single ingress for HTTP/HTTPS:

- **One TLS surface.** Public DNS for every site you publish points at the
  hub (it's the only host with a stable public address). Centralising
  Caddy there means one cert store, one Caddyfile, one ACME account.
- **No new Docker on the hub.** `docker_runtime` is only deployed to
  `app_servers`. Putting Caddy in a container on the hub would install
  Docker just for it - running it natively from the Debian repo is
  cleaner.
- **HTTP-01 ACME works out of the box.** The hub has port 80 reachable
  from the internet, so Let's Encrypt validation needs no DNS plugin or
  shared secret with your registrar.
- **Backends are reachable as `10.10.0.X:<port>` over WG.** The hub
  already routes the tunnel, so `reverse_proxy 10.10.0.2:8080` Just Works
  with no extra firewall surgery.

The hub-and-spoke topology means every public request lands on the hub
anyway (it's the only public-IP host). Whether Caddy sits there or on an
app server, the bytes pass through the hub. Putting Caddy on the hub
just removes one redundant TCP-proxy hop.

## Layout

Source-of-truth lives on the controller, mirrored verbatim to `/etc/caddy/`:

```
configs/<env>/caddy/
├── Caddyfile               # main config (required)
└── conf.d/                 # optional snippets
    ├── public.caddy
    └── internal.caddy
```

Pull snippets in from the main Caddyfile with:

```caddy
import /etc/caddy/conf.d/*.caddy
```

Snippet order is undefined - each `*.caddy` file must contain complete
site blocks, not fragments.

Every change to either the Caddyfile or any snippet runs `caddy validate`
**before** reloading the service. A typo never takes existing sites
down.

## Opting out

If `configs/<env>/caddy/` does not exist on the controller, the role
becomes a no-op: Caddy is not installed, no firewall ports are opened,
nothing changes. Use this to keep the role in `playbooks/site.yml`
without paying any cost on environments that don't need a reverse proxy
yet.

If the directory exists but is empty (no `Caddyfile`), the role fails
loudly - that's almost certainly a mistake.

## TLS modes

### `tls internal` (default for VPN-only sites)

```caddy
whoami.home {
    tls internal
    reverse_proxy 10.10.0.2:8080
}
```

Caddy mints certs from its own local CA. Clients see a warning unless they
trust the CA root once (`/var/lib/caddy/.local/share/caddy/pki/authorities/local/root.crt`
on the hub). Perfect for `*.home` names that resolve through `dnsmasq`
and only exist inside the tunnel.

### `acme` HTTP-01 (default for public sites)

```caddy
{
    email admin@example.com
}

app.example.com {
    reverse_proxy 10.10.0.2:3000
}
```

Requires:
- Public DNS A/AAAA for `app.example.com` → hub's public IP.
- Inbound 80/tcp reachable on the hub (UFW handled by the role; if the
  hub is behind NAT, forward 80 on the router too).
- `email` set in the global block.

### `acme` DNS-01 (for wildcards / hosts without public 80)

```caddy
*.example.com {
    tls {
        dns cloudflare {env.CF_API_TOKEN}
    }
    reverse_proxy 10.10.0.2:3000
}
```

Needs a DNS provider plugin compiled into Caddy. The Debian package
ships only the stock build - switch to `xcaddy` or the official "with
DNS" build if you go this route.

## Firewall

The role manages its own UFW rules; you do not add anything to
`firewall_allow_rules` for Caddy itself:

| Port | Why |
|---|---|
| 80/tcp | HTTP + ACME HTTP-01 challenge |
| 443/tcp | HTTPS |
| 443/udp | HTTP/3 (QUIC) |

Knobs (`roles/caddy/defaults/main.yml`):

```yaml
caddy_open_firewall: true        # set false to manage UFW yourself
caddy_firewall_from: [any]       # restrict to CIDRs for VPN-only exposure
caddy_open_http: true            # leave on unless you're sure no site uses ACME HTTP-01
caddy_open_https: true           # 443/tcp + 443/udp together
```

Common tightenings:

```yaml
# Only WG peers can hit Caddy (no public web)
caddy_firewall_from:
  - 10.10.0.0/24
```

```yaml
# Public site without HTTP/3
caddy_open_https: true
# (leave the rest at defaults; the role will still open 443/udp, just
#  don't expect QUIC unless you announce Alt-Svc - most browsers will
#  fall back to TCP cleanly)
```

## Site-block patterns

### One backend behind one hostname

```caddy
git.example.com {
    reverse_proxy 10.10.0.2:3000
}
```

### Multiple backends on different app servers

```caddy
git.example.com {
    reverse_proxy 10.10.0.2:3000      # forgejo on app-1
}

files.example.com {
    reverse_proxy 10.10.0.3:3923      # copyparty on app-2
}
```

### Split internal / public copies of one app

```caddy
git.example.com {
    reverse_proxy 10.10.0.2:3000
}

git.home {
    tls internal
    reverse_proxy 10.10.0.2:3000
}
```

Then add `git.home → 10.10.0.1` to `dnsmasq_extra_hosts` so WG peers
reach the internal copy without going through public DNS.

### Static file root

```caddy
files.home {
    tls internal
    root * /srv/files
    file_server browse
}
```

(Note: serves files from the hub's filesystem, not from an app server.)

## LAN bandwidth - when the hub becomes a bottleneck

The hub-on-VPS topology means a laptop on the same LAN as `app-1`,
downloading a 50 GB file from `copyparty` on `app-1` via
`copyparty.example.com`, routes every byte through the VPS in Frankfurt.
Bandwidth = VPS uplink, latency = round-trip to Frankfurt and back.

For the typical homelab UI traffic (Forgejo dashboards, monitoring,
config screens) this is invisible. For bulk file transfers it hurts.

**Escape hatch - second Caddy on the app server as a Docker stack:**

```
configs/<env>/stacks/<app-hostname>/caddy-lan/
├── compose.yaml
└── Caddyfile
```

`compose.yaml`:

```yaml
services:
  caddy:
    image: caddy:2-alpine
    container_name: caddy-lan
    restart: unless-stopped
    ports: ["80:80", "443:443"]
    volumes:
      - ./Caddyfile:/etc/caddy/Caddyfile:ro
      - caddy_data:/data
volumes:
  caddy_data:
```

`Caddyfile`:

```caddy
copyparty.home {
    tls internal
    reverse_proxy localhost:3923
}
```

Add `copyparty.home → 192.168.1.10` (LAN IP of `app-1`) to
`dnsmasq_extra_hosts`. Now LAN clients hit the local Caddy directly
(gigabit), while `copyparty.example.com` on the hub continues to work
for remote access.

No new roles or magic - `compose_deploy` already auto-discovers per-host
stacks under `configs/<env>/stacks/<hostname>/`.

## Troubleshooting

### Validate a config without deploying

```bash
caddy validate --adapter caddyfile --config configs/<env>/caddy/Caddyfile
```

(On any machine with Caddy installed - same binary the role uses.)

### See what Caddy is doing on the hub

```bash
ssh hub
journalctl -u caddy -f          # live logs
sudo systemctl status caddy     # service state + recent log lines
sudo caddy adapt --config /etc/caddy/Caddyfile | jq .   # rendered JSON config
```

### Why is my browser warning about the cert?

If you used `tls internal`, that's expected - Caddy minted the cert from
its own CA. Trust the local root cert (once per browser/system):

```bash
ssh hub
sudo cat /var/lib/caddy/.local/share/caddy/pki/authorities/local/root.crt
# Copy into your local trust store; on Linux:
sudo cp <pasted file> /usr/local/share/ca-certificates/caddy-hub.crt
sudo update-ca-certificates
```

For browsers, import the same `.crt` via their certificate manager.

### Reload didn't pick up my changes

The role runs `systemctl reload caddy`. If the config has a syntax
error, validate failed during sync and the file was never written -
check the playbook output. If validate passed but Caddy still serves
the old config, force a full restart:

```bash
sudo systemctl restart caddy
```

(Reload is graceful and almost always sufficient - restart drops
in-flight connections.)
