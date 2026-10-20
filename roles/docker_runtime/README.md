# docker_runtime

Installs Docker Engine and the Compose plugin from Docker's official apt
repository, and manages a small `daemon.json` (log rotation by default).

This role only installs and configures the runtime. It does not deploy
workloads - that is the `compose_deploy` role (see the [project
README](../../README.md#applications-app_servers-only)).

## What it does

1. Installs the apt prerequisites (`ca-certificates`, `curl`,
   `python3-debian`).
2. Adds Docker's signing key to `/etc/apt/keyrings/docker.asc` and
   configures the upstream Debian repo (suite taken from the host's
   `distribution_release`, architecture normalised from `x86_64`/
   `aarch64`).
3. Installs `docker-ce`, `docker-ce-cli`, `containerd.io`,
   `docker-buildx-plugin`, `docker-compose-plugin`.
4. Writes `/etc/docker/daemon.json` with json-file log rotation and any
   extra daemon keys, then reloads the daemon (SIGHUP - running
   containers stay up).
5. Enables and starts `docker`, and adds `docker_runtime_users` (the
   interactive admin user by default) to the `docker` group.

## Variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `docker_runtime_packages` | Docker CE + CLI + containerd + buildx + compose | Packages to install |
| `docker_runtime_apt_suite` | host's `distribution_release` | Docker repo suite |
| `docker_runtime_service_enabled` | `true` | Enable at boot |
| `docker_runtime_service_state` | `started` | Runtime state |
| `docker_runtime_manage_daemon_json` | `true` | Set `false` to leave `daemon.json` unmanaged |
| `docker_runtime_log_driver` | `json-file` | Container log driver |
| `docker_runtime_log_opts` | `max-size: 10m`, `max-file: 3` | Per-container log cap |
| `docker_runtime_daemon_extra` | `{}` | Extra `daemon.json` keys, merged on top |
| `docker_runtime_users` | `[admin_user_name]` if set, else `[]` | Members of the `docker` group |

### Log rotation

Without rotation, `json-file` logs grow until they fill the disk - the
classic self-hosting outage. The defaults cap each container at
**3 × 10 MiB = 30 MiB**:

```json
{
  "log-driver": "json-file",
  "log-opts": { "max-size": "10m", "max-file": "3" }
}
```

`docker_runtime_daemon_extra` is merged over these keys, so adding e.g.
`default-address-pools` or `dns` does not require restating them.

Daemon reload applies to **new** containers only. Containers created
before the change keep their old log settings until recreated
(`docker compose up -d --force-recreate`); the role prints a reminder
when `daemon.json` changes. Stacks deployed afterwards inherit the
defaults automatically.

## Docker and the host firewall

The `firewall` role configures UFW, but **UFW does not filter container
traffic**. Docker writes its own iptables/nftables rules, so a port
published with `ports:` bypasses UFW's `INPUT` chain entirely - a
`ufw deny` for that port has no effect, and the container is reachable
anywhere the host is.

Practical rules:

- Bind published ports to a private address instead of `0.0.0.0`:
  `"10.10.0.2:8080:8080"` (the peer's WireGuard IP) or
  `"127.0.0.1:9090:9090"` (host only).
- Or publish nothing and let Caddy reverse-proxy the stack.
- If you need host-level filtering, manage the `DOCKER-USER` chain
  yourself - this role does not touch it.

Full explanation and examples:
[Docker bypasses UFW](../firewall/README.md#docker-bypasses-ufw).
