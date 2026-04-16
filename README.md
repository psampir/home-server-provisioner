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

### 2. Configure environment

Copy the example environment file and adjust if needed:

```bash
cp .env.example .env
```

The defaults work for most setups. Override `SSH_PUBKEY_FILE` if your key isn't `~/.ssh/id_ed25519.pub`.

### 3. Create your inventory

```bash
cp inventories/production/hosts.yml.example inventories/production/hosts.yml
```

Edit `hosts.yml` and add your hosts. Each host needs:

- `ansible_host` - the IP address or hostname
- `bootstrap_user` - the SSH user on a fresh install (e.g., `ubuntu`, `root`)

```yaml
app_servers:
  hosts:
    my-server:
      ansible_host: 10.0.0.1
      bootstrap_user: jan
```

A host can belong to multiple groups:

| Group | Purpose |
|---|---|
| `app_servers` | Docker, Compose, Caddy, workloads |
| `backup_targets` | Backup storage, borgmatic destinations |
| `vpn_servers` | WireGuard listening endpoint |

### 4. Bootstrap (first run only)

```bash
make bootstrap
```

This connects as each host's `bootstrap_user`, creates a dedicated `ansible` user with sudo and SSH key access. Run this once per host.

### 5. Provision

```bash
make provision
```

Runs the full provisioning playbook as the `ansible` user. Safe to re-run - all tasks are idempotent.

## What it does

| Role | Description |
|---|---|
| `users` | Creates dedicated `ansible` user with passwordless sudo and SSH key |
| `common` | Updates apt cache, installs common packages |
| `ssh_hardening` | Disables root login and password authentication |

More roles (Docker, Caddy, WireGuard, borgmatic) are planned.

## Repository layout

```
├── ansible.cfg                          # Ansible configuration
├── requirements.yml                     # Required Ansible collections
├── Makefile                             # Project entry point
├── .env.example                         # Environment variable template
├── docs/
│   └── deployment-guide.md              # Multi-site deployment scenarios
├── inventories/
│   ├── test/                            # Auto-generated test inventory
│   └── production/
│       ├── hosts.yml.example            # Inventory template
│       └── group_vars/
│           └── all.yml                  # Shared variables
├── playbooks/
│   ├── bootstrap.yml                    # First-run user setup
│   └── site.yml                         # Full provisioning
├── roles/
│   ├── common/                          # Base packages
│   ├── users/                           # Admin user management
│   └── ssh_hardening/                   # SSH server hardening
└── scripts/
    ├── setup.sh                         # Dependency installer
    ├── test-env.sh                      # Multipass test VM manager
    └── test-vms.conf                    # Test VM definitions
```

## Testing

The project includes tooling for local testing with [Multipass](https://multipass.run) VMs:

```bash
make test-env-create    # Launch test VMs
make bootstrap          # Bootstrap the ansible user
make provision          # Run full provisioning
make test-env-destroy   # Tear down VMs
```

## Further reading

- [Deployment Guide](docs/deployment-guide.md) - multi-site setups, off-site hosts, and VPN connectivity

## License

[Apache 2.0](LICENSE)
