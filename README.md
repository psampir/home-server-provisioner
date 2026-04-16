# home-server-provisioner

Ansible-based provisioning toolkit for Ubuntu self-hosted servers.

Prepares fresh Ubuntu hosts with system hardening, a dedicated management user, and a baseline configuration - ready for Docker workloads, reverse proxying, VPN connectivity, and automated backups.

## Supported platform

- Ubuntu Server 24.04 LTS

## Prerequisites

- A control machine (macOS or Linux) with SSH access to your servers
- An SSH key pair (`ssh-keygen` if you don't have one)
- [Homebrew](https://brew.sh) or [pipx](https://pipx.pypa.io) for installing Ansible

## Quick start

### 1. Install dependencies

```bash
make setup
```

This installs Ansible, ansible-lint, and required collections. It auto-detects Homebrew or pipx, or you can specify:

```bash
./scripts/setup.sh brew    # or: ./scripts/setup.sh pipx
```

### 2. Set up your configuration

```bash
make init-config
```

This creates a `config/` directory with your private settings (`.env`, inventory, variables) and symlinks them into place. The directory is its own git repo - you can push it to a private remote to back up your config.

Edit `config/inventory/hosts.yml` and add your hosts. Each host needs:

- `ansible_host` - the IP address or hostname
- `bootstrap_user` - the SSH user on a fresh install (e.g., `ubuntu`, `root`)

```yaml
app_servers:
  hosts:
    my-server:
      ansible_host: 10.0.0.1
      bootstrap_user: jan
```

Edit `config/inventory/group_vars/all.yml` to configure roles. All options have sensible defaults - uncomment and adjust what you need.

Edit `config/.env` if your SSH key isn't `~/.ssh/id_ed25519`.

A host can belong to multiple groups:

| Group | Purpose |
|---|---|
| `app_servers` | Docker, Compose, Caddy, workloads |
| `backup_targets` | Backup storage, borgmatic destinations |
| `vpn_servers` | WireGuard listening endpoint |

### 3. Bootstrap (first run only)

```bash
make bootstrap
```

This connects as each host's `bootstrap_user`, creates a dedicated `ansible` user with sudo and SSH key access. Run this once per host.

### 4. Provision

```bash
make provision
```

Runs the full provisioning playbook as the `ansible` user. Safe to re-run - all tasks are idempotent.

## What it does

| Role | Description |
|---|---|
| `service_user` | Creates dedicated `ansible` service account with passwordless sudo and SSH key |
| `base` | Updates apt cache, upgrades packages, installs base packages |
| `admin_user` | Interactive SSH user with configurable shell and packages |
| `ssh_hardening` | Disables root login and password authentication |
| `ssh_config` | Generates `~/.ssh/config.d` entries on the control machine |

More roles (Docker, Caddy, WireGuard, borgmatic) are planned.

## Testing

The project includes tooling for local testing with [Multipass](https://multipass.run) VMs:

```bash
make test-env-create    # Launch test VMs
make test-bootstrap     # Bootstrap the ansible user
make test-provision     # Run full provisioning
make test-env-destroy   # Tear down VMs
```

## Further reading

- [Deployment Guide](docs/deployment-guide.md) - multi-site setups, off-site hosts, and VPN connectivity

## License

[Apache 2.0](LICENSE)
