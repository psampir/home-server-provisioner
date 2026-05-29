# Deployment Guide

This document covers common deployment scenarios, including provisioning off-site hosts and managing hosts across different networks.

## Single-site setup

If all hosts are on the same local network as the control machine, provisioning is straightforward:

1. Set `ansible_host` to each host's local IP.
2. Run `make bootstrap` then `make provision`.
3. Re-run `make provision` any time you update configuration.

## Multi-site setup with off-site hosts

Off-site hosts (e.g., a remote backup server) are not directly reachable from the control machine once deployed. The recommended approach is to **provision the host locally before moving it** to its final location.

### Workflow

#### 1. Provision at home

While the host is still on the local network:

```yaml
# configs/prod/inventory/hosts.yml
backup_targets:
  hosts:
    offsite-backup:
      ansible_host: 192.168.1.50    # local IP while at home
      bootstrap_user: jan
```

Run the full provisioning, including the WireGuard role (when available):

```bash
make bootstrap
make provision
```

At this point the host has WireGuard configured and will connect to the VPN hub automatically once it has internet access.

#### 2. Move the host to its remote location

Ship or carry the host to the off-site location. Once it powers on and gets internet access, it connects to the WireGuard VPN automatically.

#### 3. Update the inventory to use the VPN address

```yaml
backup_targets:
  hosts:
    offsite-backup:
      ansible_host: 10.0.0.50       # WireGuard VPN IP
      bootstrap_user: jan
```

From this point on, `make provision` reaches the host through the VPN.

### Why not provision remotely?

Provisioning a host that has no VPN and no public IP is not possible - Ansible needs SSH access. Exposing SSH to the internet is an option but introduces unnecessary risk for a one-time setup.

Provisioning locally before deployment avoids this entirely and ensures the host arrives at its destination ready to connect.

## Updating ansible_host after network changes

The `ansible_host` value in your inventory should always reflect how the control machine can currently reach the host:

| Scenario | ansible_host |
|---|---|
| Host on the same LAN | Local IP (e.g., `192.168.1.x`) |
| Host reachable via VPN | VPN IP (e.g., `10.0.0.x`) |
| Host with a public IP | Public IP or DNS name |

If a host moves between networks, update `ansible_host` accordingly. This is a one-time change per host - once the VPN is active, the VPN IP is stable.
