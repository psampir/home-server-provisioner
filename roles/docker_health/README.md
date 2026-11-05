# docker_health

Reports Docker container health to a [Gatus](https://gatus.io) external
endpoint, so containers without a published port are monitored too. The
script reads the Docker socket on the host, so no port or API is exposed.

## What it does

1. Renders `/etc/hsp/docker-health.env` (mode `0600`, it holds the token).
2. Installs `/usr/local/bin/hsp-docker-health`.
3. Leaves the timer to `scheduled_jobs`, so the interval and the failure
   notification stay an environment decision.

Every run inspects the containers in `docker_health_require_healthy`
(must be running with a passing healthcheck) and
`docker_health_require_running` (no healthcheck, must be running), then
pushes one aggregate status to Gatus. A container that is missing,
stopped, starting, unhealthy or no longer has a healthcheck is reported by
name.

Containers also listed in `docker_health_per_container` get an extra
informational endpoint `<prefix>_<container>`, so the dashboard shows one
row per container instead of a single boolean. Only the aggregate
endpoint carries alerts and the heartbeat, so a dead script pages once
rather than once per container.

Gatus raises the alert, and its endpoint heartbeat (3 minutes) catches the
case where the script stops running or cannot reach Gatus. A transient TLS
or network failure during a Caddy reload is retried and is not paged as a
systemd unit failure; the heartbeat is the watchdog for the monitoring path.

## Variables

| Variable | Default | Description |
|---|---|---|
| `docker_health_enabled` | `false` | Master switch |
| `docker_health_gatus_url` | `""` | Gatus base URL, e.g. `http://10.10.0.1:8080` |
| `docker_health_endpoint_key` | `""` | `<group>_<name>`, e.g. `apps_docker-health` |
| `docker_health_token` | `""` | Bearer token, keep it in the vault |
| `docker_health_gatus_ca` | `""` | Optional CA bundle to verify the Gatus certificate |
| `docker_health_require_healthy` | `[]` | Containers that must be healthy |
| `docker_health_require_running` | `[]` | Containers that only need to run |
| `docker_health_per_container` | `[]` | Containers that also get their own row; must be in one of the lists above |
| `docker_health_endpoint_prefix` | `docker` | Prefix of the per-container endpoint key |
| `docker_health_timeout` | `10` | Push timeout in seconds |

The endpoint key is the group and name lowercased, with spaces, slashes,
underscores, dots, hashes, pluses and ampersands replaced by a dash.

## Gatus side

```yaml
external-endpoints:
  - name: docker-health
    group: apps
    token: "{{ vault_gatus_push_token }}"
    heartbeat:
      interval: 3m
    alerts:
      - type: ntfy
        failure-threshold: 3
        success-threshold: 2
        send-on-resolved: true
```

A `3m` heartbeat with a one minute job leaves room for one or two missed
runs without a false alert, while a dead script still pages within minutes.

Each container in `docker_health_per_container` needs its own endpoint in
the same `docker` group, with no alerts:

```yaml
  - name: bta-controller
    group: docker
    token: "{{ vault_gatus_push_token }}"
    heartbeat:
      interval: 3m
    alerts: []
```

The key is `<group>_<name>`, so the container name must match what the
script slugifies: underscores become dashes.

If Gatus sits behind a reverse proxy with an internal CA, set
`docker_health_gatus_ca` to that CA root and point
`docker_health_gatus_url` at the HTTPS name. The push then verifies the
certificate instead of disabling verification.

## Scheduling

```yaml
scheduled_jobs_common:
  - name: docker-health
    command: /usr/local/bin/hsp-docker-health
    schedule: "*-*-* *:*:00"
    description: "Push Docker container health to Gatus"
    notify_on_failure: true
```

The job runs as root, which is what reading the Docker socket requires.
