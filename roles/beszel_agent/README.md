# beszel_agent

Installs the Beszel agent as a pinned Go binary and a systemd service. The
agent connects outbound to the hub over WebSocket, so no inbound port is
needed. It is disabled by default and only runs when a hub URL, key and
token are supplied.

## What it does

1. Downloads the pinned agent release and verifies its SHA-256 checksum.
2. Creates the `beszel` system user and `/var/lib/beszel-agent`.
3. Renders `/etc/beszel-agent.env` with the hub URL, key, token and system
   name (mode 0600, `no_log`).
4. Installs and starts `beszel-agent.service` with journal access.
5. Optionally enables Docker container monitoring by adding the service to
   the `docker` group.

## Variables

| Variable | Default | Description |
|---|---|---|
| `beszel_agent_enabled` | `false` | Install and start the agent |
| `beszel_agent_version` | `0.21.1` | Pinned release |
| `beszel_agent_binary_url` | GitHub release | Agent archive URL |
| `beszel_agent_binary_sha256` | pinned | Archive checksum |
| `beszel_agent_hub_url` | empty | Hub URL, e.g. `http://10.10.0.2:8090` |
| `beszel_agent_key` | empty | Hub public key |
| `beszel_agent_token` | empty | Universal or system token |
| `beszel_agent_system_name` | `inventory_hostname` | Name shown in the hub |
| `beszel_agent_docker` | `false` | Monitor Docker containers on this host |
| `beszel_agent_data_dir` | `/var/lib/beszel-agent` | Fingerprint/data directory |
| `beszel_agent_smart_devices` | empty | SMART device list; empty disables SMART polling |

## Docker monitoring

The binary agent reads `/var/run/docker.sock` through the `docker` group.
That is root-equivalent for reads. Enable it only on Docker hosts and only
if the trade-off is acceptable; the alternative is a socket proxy.

## Updating

Bump `beszel_agent_version` and `beszel_agent_binary_sha256` together. The
role re-downloads, reinstalls and restarts the service. Do not use
`latest`, and do not enable the install script's automatic updates.
