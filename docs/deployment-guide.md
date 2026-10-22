# Deployment Guide

This guide covers the common deployment paths: a single-site fleet, an
off-site host that moves after provisioning, and the checks to run after a
cutover.

## Before you start

1. Create the environment and its vault:

   ```bash
   make init-config ENV=prod
   make vault-init ENV=prod
   ```

2. Fill in `configs/prod/inventory/hosts.yml`, the group vars, and the
   host vars. The example tree is the reference:
   `configs/example/inventory/`.
3. Put secrets in `configs/prod/inventory/group_vars/all/vault.yml`. The
   plain-text template lists every value the roles consume.
4. Make sure the control machine can reach the hosts over SSH with the key
   in `.env`.

## Single-site setup

If every host is on the same LAN as the control machine, provisioning is
direct:

1. Set `ansible_host` to each host's LAN address.
2. Run the bootstrap once per host, then the full site play:

   ```bash
   make bootstrap ENV=prod
   make provision ENV=prod
   ```

3. Re-run `make provision ENV=prod` after configuration changes. The
   playbook is idempotent; a second run should report `changed=0` for
   unchanged hosts.
4. Generate the controller SSH aliases:

   ```bash
   make ssh-config ENV=prod
   ```

   Then `ssh <hostname>` works for every host in the `servers` group.

## Multi-site setup with off-site hosts

An off-site host is not reachable from the control machine once it leaves
the LAN. Provision it locally first, then move it. The WireGuard tunnel is
what makes it reachable afterwards.

### 1. Provision at home

Keep the host on the local network and use its LAN address:

```yaml
# configs/prod/inventory/hosts.yml
backup_targets:
  hosts:
    offsite-backup:
      ansible_host: 192.168.1.50    # local IP while at home
      bootstrap_user: jan
```

Run the full provisioning. This includes the WireGuard role, which writes
the peer configuration and connects the host to the hub:

```bash
make bootstrap ENV=prod
make provision ENV=prod
```

At this point the host has WireGuard configured and will connect
automatically once it has internet access.

### 2. Make the control machine a VPN client

The controller must be able to reach `10.10.0.x` before you switch
`ansible_host` to a VPN address. Add the controller to the client list:

```yaml
# configs/prod/inventory/group_vars/all/main.yml
wireguard_clients:
  - name: "Control laptop"
    vpn_ip: 10.10.0.21
    allowed_ips: "10.10.0.0/24"
```

Generate the key if the client is new, then render the configuration:

```bash
make wireguard-keys ENV=prod
make wireguard-render ENV=prod
```

The file is written to
`build/prod/wireguard/<client>.conf`. Import it with NetworkManager or start
it with `wg-quick`, then verify:

```bash
wg show
ping -c 3 10.10.0.1
getent hosts <a-managed-host>
```

Do this **before** the cutover. Without a tunnel on the controller,
`10.10.0.x` is unreachable.

### 3. Move the host

Ship or carry the host to the off-site location. Once it powers on and gets
internet access, it connects to the hub.

### 4. Switch the inventory to the VPN address

```yaml
backup_targets:
  hosts:
    offsite-backup:
      ansible_host: 10.10.0.50       # WireGuard VPN IP
      bootstrap_user: jan
```

From this point on, `make provision` reaches the host through the tunnel.

### 5. Verify before the next change

```bash
make plan ENV=prod LIMIT=offsite-backup
make provision ENV=prod LIMIT=offsite-backup
```

If the host does not answer, check the hub first: `wg show` on the hub
should list a recent handshake, and the peer's `AllowedIPs` must include
the address you put in `ansible_host`.

### Why not provision remotely?

Provisioning a host with no VPN and no public IP is not possible because
Ansible needs SSH access. Exposing SSH to the internet is an option, but it
adds risk for a one-time setup. Provisioning locally avoids that and leaves
the host ready to connect when it arrives.

## Backup target order

`borgmatic` (source) runs in the early `servers` play. `borg_repo` (target)
runs in the later `backup_targets` play. On a first provision the target
repository does not exist yet, so the source preflight only warns by
default.

Recommended order:

```bash
make provision ENV=prod LIMIT=backup-host
make provision ENV=prod LIMIT=app-host
```

To make the source fail when the target is missing, set
`borgmatic_require_reachable: true` in the source host vars. See
[roles/borgmatic/README.md](../roles/borgmatic/README.md#provisioning-order-target-first-source-second).

## Updating and rollback

- The environment tree is its own git repository. Commit inventory and
  stack changes there before provisioning.
- Re-provision after reverting a commit. The playbook converges the host
  back to the committed state.
- This toolkit does not roll back application data. Use the backup and
  restore procedure in [docs/backups.md](backups.md), or the host's own
  snapshot mechanism, before destructive changes.
- For a read-only preview, `make plan ENV=prod LIMIT=<host>` lists the
  tasks that would run. It does not execute them. A full `--check` run is
  possible with `ansible-playbook`, but some roles need real changes before
  later tasks can be evaluated.

## Updating ansible_host after network changes

`ansible_host` should always reflect how the control machine can currently
reach the host:

| Scenario | ansible_host |
|---|---|
| Host on the same LAN | Local IP (for example `192.168.1.x`) |
| Host reachable via VPN | VPN IP (for example `10.10.0.x`) |
| Host with a public IP | Public IP or DNS name |

When a host moves between networks, update `ansible_host` and re-run
`make provision`. The VPN address is stable once the tunnel is active.
