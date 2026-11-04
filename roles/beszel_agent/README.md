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
| `beszel_agent_extra_filesystems` | empty | Comma-separated mountpoints/devices for extra disk charts |
| `beszel_agent_requires_mounts` | `[]` | Mountpoints the service waits for (`RequiresMountsFor`) |
| `beszel_agent_gpu_collector` | empty | Comma-separated GPU collectors, e.g. `intel_gpu_top` |
| `beszel_agent_perf_event_paranoid` | `2` | `kernel.perf_event_paranoid` set when `intel_gpu_top` is used |
| `beszel_agent_smart_exclude` | empty | Comma-separated devices skipped by SMART |
| `beszel_agent_extra_groups` | `[]` | Supplementary groups for the service |
| `beszel_agent_capabilities` | `[]` | Ambient capabilities for the service |

## Docker monitoring

The binary agent reads `/var/run/docker.sock` through the `docker` group.
That is root-equivalent for reads. Enable it only on Docker hosts and only
if the trade-off is acceptable; the alternative is a socket proxy.

## Extra filesystems

`EXTRA_FILESYSTEMS` accepts mountpoints or devices, so a data disk mounted
outside `/` gets its own usage chart. The variable is only rendered when it
is non-empty: an empty value is parsed as an invalid filesystem.

The agent discovers filesystems once, at start-up, so an entry that points
at a mountpoint must already be mounted. If the service starts first (for
example on a USB disk that appears late during boot), it resolves the
directory on the root filesystem and registers that as a separate disk named
after the directory (e.g. `data` instead of `sdb1`), and it never retries
after the disk is mounted. Set `beszel_agent_requires_mounts` to the same
mountpoints to add `RequiresMountsFor=` to the unit and make systemd start
the agent only after they are mounted:

```yaml
beszel_agent_extra_filesystems: "/srv/data"
beszel_agent_requires_mounts:
  - /srv/data
```

## GPU

`GPU_COLLECTOR=intel_gpu_top` needs `intel-gpu-tools`, the `video` and
`render` groups, and `CAP_PERFMON` on kernels with
`perf_event_paranoid >= 2`. `intel_sysfs` instead needs a hwmon
`energy1_input`, which older iGPUs such as Gemini Lake and Haswell lack.

On Debian's 6.12 kernel CAP_PERFMON alone is not enough: at
`perf_event_paranoid=3` `perf_event_open` on the i915 PMU still returns
`EACCES`, so `intel_gpu_top` reports `Failed to initialize PMU` and the
agent logs `no valid GPU data found`. When `intel_gpu_top` is selected the
role therefore writes `kernel.perf_event_paranoid=2` to
`/etc/sysctl.d/99-beszel-gpu.conf` (see
`beszel_agent_perf_event_paranoid`) and restarts the agent. Hosts without
that collector keep the system default.

## SMART

A non-empty `SMART_DEVICES` enables polling; an empty value disables it.
smartctl needs the `disk` group and `CAP_SYS_RAWIO`; `CAP_SYS_ADMIN` is not
required for SATA. Entries may be `path:type`, e.g. `/dev/sdb:sat`.

## Updating

Bump `beszel_agent_version` and `beszel_agent_binary_sha256` together. The
role re-downloads, reinstalls and restarts the service. Do not use
`latest`, and do not enable the install script's automatic updates.
