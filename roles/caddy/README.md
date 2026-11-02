# caddy

Installs Caddy natively on the WireGuard hub and manages its configuration
from the controller.

This is the native role variant. The same project also supports Caddy as a
Compose stack on an app server. See [docs/caddy.md](../../docs/caddy.md) for
both variants and for the recommended stack-based ingress.

## What it does

1. Picks the source directory for this host: `caddy_source_dir` joined with
   `caddy_host_subdir` when that exists, otherwise `caddy_source_dir` itself
   as a single-host fallback. If neither exists, the role is a no-op: Caddy
   is not installed and no firewall ports are opened.
2. Fails loudly if the directory exists but has no `Caddyfile`.
3. Installs the `caddy` package.
4. Syncs `Caddyfile` to `/etc/caddy/Caddyfile` with mode `0640`.
5. Syncs `conf.d/*.caddy` snippets, validates the full configuration with
   `caddy validate`, and removes snippets that no longer exist on the
   controller.
6. Enables and starts `caddy`.
7. Opens 80/tcp, 443/tcp, and 443/udp in UFW when configured.

Every file change is validated before the reload handler runs, so a typo
does not take existing sites down.

## Variables

| Variable | Default | Description |
|---|---|---|
| `caddy_source_dir` | `configs/<env>/caddy` | Base directory with one `Caddyfile` and optional `conf.d/` per host, or a flat layout |
| `caddy_host_subdir` | `inventory_hostname` | Subdirectory picked under `caddy_source_dir` |
| `caddy_notify_failures` | `true` | Add `OnFailure=hsp-notify-failure@` to the service |
| `caddy_apt_repo` | `false` | Install from the official Caddy repository instead of Debian |
| `caddy_apt_key_url` | Cloudsmith key | Repository signing key |
| `caddy_apt_keyring` | `/usr/share/keyrings/caddy-stable-archive-keyring.asc` | Downloaded key |
| `caddy_apt_sources` | `/etc/apt/sources.list.d/caddy-stable.list` | Repository definition |
| `caddy_apt_repo_line` | `deb ... any-version main` | Repository line |
| `caddy_open_firewall` | `true` | Open Caddy ports in UFW |
| `caddy_firewall_from` | `[any]` | Source CIDRs for the firewall rules |
| `caddy_open_http` | `true` | Open 80/tcp for ACME HTTP-01 |
| `caddy_open_https` | `true` | Open 443/tcp for HTTPS |
| `caddy_open_http3` | `true` | Open 443/udp for HTTP/3; requires `caddy_open_https` |

## Notes

- The role is safe to leave in `playbooks/site.yml` for environments that
  do not use it. Create `configs/<env>/caddy/` only when you want the native
  hub variant.
- Layout: `configs/<env>/caddy/<hostname>/Caddyfile` wins over
  `configs/<env>/caddy/Caddyfile`, so several hosts can each have their own
  sites. The flat file stays supported for single-host environments and is
  reported as a fallback in the task output.
- `caddy_open_https` controls HTTPS on 443/tcp. `caddy_open_http3` controls
  443/udp and only takes effect when HTTPS is enabled.
- The role manages `/etc/caddy/conf.d/*.caddy` and removes orphaned
  snippets. Do not put unmanaged files in that directory.
- For a Compose stack on an app server, use `compose_deploy` instead. That
  variant publishes container ports directly, which bypasses UFW; see
  [roles/firewall/README.md](../firewall/README.md#docker-bypasses-ufw).
- The Caddy service runs as the `caddy` user. Certificate and data paths
  depend on the packaging and are not managed by this role.
- Debian trixie ships Caddy 2.6, which predates named PKI authorities. A
  Caddyfile that uses `pki { ca ... }` and `issuer internal { ca ... }`
  is rejected there. Set `caddy_apt_repo: true` to install the upstream
  release instead, so the hub speaks the same Caddyfile dialect as a
  `caddy:<tag>` Compose stack on an app server.
- The named CA also decides the storage directory. With `ca internal` the
  material lives in `pki/authorities/internal/`; Debian's 2.6 `tls internal`
  keeps it in `pki/authorities/local/`. Sharing one CA between hosts means
  matching the CA name, not copying between those directories.
