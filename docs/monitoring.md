# Monitoring

The toolkit ships a small self-hosted monitoring stack: one dashboard on
the hub, push endpoints for things that do not answer HTTP, and an external
heartbeat that acts as a dead man's switch. Everything routes to `ntfy`;
email is the independent second channel.

## Roles

| Role | Purpose |
|---|---|
| `gatus` | Dashboard and checker for HTTP, TCP, DNS and TLS, ntfy alerts, optional external heartbeat |
| `docker_health` | Pushes container health to a Gatus external endpoint without exposing the Docker socket |
| `notifications` | `hsp-notify` CLI, the ntfy backend and `hsp-disk-check` |
| `login_notify` | PAM session hook that reports untrusted SSH logins |
| `smart_monitoring` | `smartd` with alerts and USB bridge quirks for enclosures that hide SMART |
| `nut` | UPS events to ntfy through `hsp-notify-ups` |

## Where the dashboard lives

Put Gatus on a host outside the site it monitors, usually the VPN hub. If it
runs on the same machine as the services, it disappears together with them.

Bind it to loopback and publish it through the reverse proxy, or bind it to
the WireGuard address. Either way, restrict the port with the firewall:
Gatus has no authentication, so the source address is the access control.
Keep the SQLite database under `/var/lib/gatus`.

## Endpoints

Group endpoints by purpose and give each group an interval that matches how
fast a problem matters. Conditions carry the real signal:

```yaml
conditions:
  - "[STATUS] == 200"
  - "[CERTIFICATE_EXPIRATION] > 240h"
```

Do not add a certificate condition for a short-lived internal CA. A CA that
issues 12-hour certificates would fail every check.

## Push endpoints

Some things cannot be checked with an HTTP request. Two patterns cover them:

- **External endpoints** receive a POST from a script. `docker_health` sends
  one aggregate status per run, named in the endpoint key, and one
  informational status per listed container. Only the aggregate carries the
  alert and the heartbeat, so a dead script pages once instead of once per
  container.
- **A heartbeat** is the dead man's switch. A timer pings an external
  service only while the local health endpoint answers. Silence means the
  hub or the dashboard stopped working, which a port check and `OnFailure`
  cannot see.

The push token is a secret. Keep it in the vault and render it into a
`0600` file on the host. Healthchecks.io offers a free heartbeat; on
UptimeRobot it is a paid feature.

## Alert routing

`ntfy` is the primary channel. Pick a priority per source:

| Priority | Sources |
|---|---|
| urgent | UPS battery low, communication with the UPS not restored |
| high | host or service down, failed unit, backup error, untrusted SSH login |
| default | warning thresholds, recovery messages |
| low | informational events |

Trusted network logins do not notify at all: they are routine and the
journal keeps the record. Only a login from somewhere else deserves a push.

Keep one channel independent of the dashboard and of the tunnel. An
external port check with email covers the hub being gone, and an external
heartbeat covers a hub that is up but no longer monitoring.

## Dead man's switch

Enable it with `gatus_heartbeat_url` on the role. A timer runs every
`gatus_heartbeat_interval` minutes, checks `gatus_heartbeat_health_url` and
pings the external URL only when it answers. The external service then
alerts on silence, with its own grace period.

## Testing

```bash
make test-gatus
make test-gatus-heartbeat
make test-docker-health
make test-disk-check
make test-login-notify
make test-nut-notify
```

For a real end-to-end check, stop a monitored service and watch the alert
and its resolution. Keep the failure threshold high enough that a restart
does not page.
