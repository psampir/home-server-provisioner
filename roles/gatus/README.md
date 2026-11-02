# gatus

Lightweight health dashboard and uptime monitor. Gatus checks HTTP,
TCP, DNS, TLS and push/heartbeat endpoints, exposes a YAML-configured
dashboard, and sends alerts through ntfy. It uses about 25 MiB of RAM,
so it fits on a small VPS.

## Install method

Gatus is not in Debian and upstream no longer publishes release
binaries. The role extracts the static binary from the official image:

```text
skopeo copy docker://ghcr.io/twin/gatus:<version> oci:...
umoci unpack ...
copy /gatus to /usr/local/bin/gatus
```

`skopeo` and `umoci` come from apt. No Docker or Node is installed on the
target. Set `gatus_binary_src` to a local static binary to skip the image
pull, for example in an air-gapped environment.

## Configuration

`gatus_config` is a dictionary rendered as the Gatus YAML. The role merges
the ntfy block from `gatus_ntfy_*` variables, so the topic can come from
the vault without nesting Jinja inside the dictionary:

```yaml
gatus_enabled: true
gatus_after_units:
  - wg-quick@wg0.service
gatus_wants_units:
  - wg-quick@wg0.service
gatus_part_of_units:
  - wg-quick@wg0.service
gatus_ntfy_topic: "{{ notifications_ntfy_url | urlsplit('path') | regex_replace('^/', '') }}"
gatus_config:
  storage:
    type: sqlite
    path: /var/lib/gatus/gatus.db
  web:
    address: 10.10.0.1
    port: 8080
  endpoints:
    - name: example
      group: apps
      url: https://example.internal
      interval: 2m
      client:
        insecure: true
      conditions:
        - "[STATUS] == 200"
        - "[CERTIFICATE_EXPIRATION] > 240h"
      alerts:
        - type: ntfy
```

The rendered file is mode `0640` owned by `root:gatus` and the template
task uses `no_log`, because the ntfy topic and push tokens are secrets.

## Security

- Gatus has no authentication. Keep `web.address` on `127.0.0.1` or a
  WireGuard address, and restrict the port with UFW to the clients that
  need the dashboard.
- The dashboard is HTTP. On a WireGuard address the tunnel provides
  encryption; do not bind it to a public interface.
- The service runs as `gatus` with `ProtectSystem=strict` and write access
  only to `/var/lib/gatus`.
- `OnFailure=hsp-notify-failure@%n.service` reports startup or config
  failures through the notifications role.

## Variables

| Variable | Default | Purpose |
|---|---|---|
| `gatus_enabled` | `false` | Master switch |
| `gatus_version` | `v5.37.0` | Image tag and version marker |
| `gatus_image` | `ghcr.io/twin/gatus` | Official image |
| `gatus_image_digest` | empty | Optional `sha256:` pin |
| `gatus_arch` | `amd64` | Image architecture |
| `gatus_binary_src` | empty | Local binary escape hatch |
| `gatus_install_tools` | `true` | Install `skopeo` and `umoci` |
| `gatus_user` / `gatus_group` | `gatus` | Service identity |
| `gatus_config_dir` | `/etc/gatus` | Config directory |
| `gatus_data_dir` | `/var/lib/gatus` | SQLite and home directory |
| `gatus_config` | `{}` | Gatus YAML as a dictionary |
| `gatus_ntfy_enabled` | `true` | Merge the ntfy alerting block |
| `gatus_ntfy_url` | `https://ntfy.sh` | ntfy server |
| `gatus_ntfy_topic` | empty | ntfy topic, required when enabled |
| `gatus_ntfy_priority` | `4` | Alert priority |
| `gatus_ntfy_failure_threshold` | `2` | Failures before alerting |
| `gatus_ntfy_success_threshold` | `2` | Successes before resolving |
| `gatus_after_units` / `gatus_wants_units` | `[]` | Extra systemd dependencies |
| `gatus_part_of_units` | `[]` | Units whose restart restarts Gatus |
| `gatus_heartbeat_url` | empty | External heartbeat URL, disabled when empty |
| `gatus_heartbeat_health_url` | `http://127.0.0.1:8080/health` | Health endpoint checked before pinging |
| `gatus_heartbeat_interval` | `5` | Minutes between pings |

## Testing

`make test-gatus` renders the config and unit templates without touching
a host. A real install is tested on the hub, then `curl` the health
endpoint:

```bash
curl -fsS http://10.10.0.1:8080/health
```

To test alerting, add a temporary endpoint with a bad URL and
`failure-threshold: 1`, confirm the ntfy alert, then remove it.

## Dead man's switch

Set `gatus_heartbeat_url` to an external heartbeat check, for example
Healthchecks.io `https://hc-ping.com/<uuid>`. The role installs
`hsp-gatus-heartbeat` and a timer that runs every
`gatus_heartbeat_interval` minutes. The script pings the URL only when
`gatus_heartbeat_health_url` answers, so the external service alerts both
when the hub disappears and when the hub is up but Gatus is not working.

An empty `gatus_heartbeat_url` disables the timer and removes its units.
UptimeRobot's heartbeat monitor is a paid feature; Healthchecks.io offers
it on the free plan with email alerts.
