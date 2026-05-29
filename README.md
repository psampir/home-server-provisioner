# home-server-provisioner

Ansible-based provisioning toolkit for Debian self-hosted servers.

Prepares fresh Debian hosts with system hardening, a dedicated management user, and a baseline configuration - ready for Docker workloads, reverse proxying, VPN connectivity, and automated backups.

## Supported platform

- Debian 13 (trixie)

## Prerequisites

- A control machine (Linux or macOS) with SSH access to your servers
- An SSH key pair (`ssh-keygen` if you don't have one)
- [Homebrew](https://brew.sh) or [pipx](https://pipx.pypa.io) for installing Ansible
- For local testing: [Incus](https://linuxcontainers.org/incus/) on a Linux workstation

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
make init-config            # default: creates configs/prod/
# make init-config ENV=lab  # or any other name; one tree per environment
```

This copies `configs/example/` to `configs/<ENV>/` and initialises a fresh git repo inside it - you can push that repo to a private remote to back up your config independently of this provisioner repo.

Edit `configs/prod/inventory/hosts.yml` and add your hosts. Each host needs:

- `ansible_host` - the IP address or hostname
- `bootstrap_user` - the SSH user on a fresh install (typically the regular user you created during the Debian installer, or `root`)

```yaml
app_servers:
  hosts:
    my-server:
      ansible_host: 10.0.0.1
      bootstrap_user: jan
```

Edit `configs/prod/inventory/group_vars/all/main.yml` to configure roles. All options have sensible defaults - uncomment and adjust what you need.

Edit `.env` if your SSH key isn't `~/.ssh/id_ed25519` (the file lives in this repo root, not in `configs/`, because it tunes the provisioner itself).

A host can belong to multiple groups:

| Group | Purpose |
|---|---|
| `app_servers` | Docker, Compose, Caddy, workloads |
| `backup_targets` | Backup storage, borgmatic destinations |
| `vpn_servers` | WireGuard listening endpoint |

### 3. Bootstrap (first run only)

```bash
make bootstrap              # ENV=prod by default
```

This connects as each host's `bootstrap_user`, creates a dedicated `ansible` user with sudo and SSH key access. Run this once per host.

### 4. Provision

```bash
make provision              # ENV=prod by default
```

Runs the full provisioning playbook as the `ansible` user. Safe to re-run - all tasks are idempotent.

### Multiple environments

Every command takes an `ENV=<name>` override. Each environment is a self-contained tree under `configs/<name>/`:

```bash
make init-config ENV=prod2          # configs/prod2/, separate git repo
make vault-init  ENV=prod2
make provision   ENV=prod2
```

## Secrets management

Sensitive material (WireGuard client private keys and PSKs) lives in
`configs/<ENV>/inventory/group_vars/all/vault.yml`, encrypted with
[ansible-vault](https://docs.ansible.com/ansible/latest/vault_guide/index.html).
You never edit this file by hand - it is auto-managed.

**Setup (one-time, per environment):**

```bash
make init-config ENV=prod   # creates configs/prod/ (its own git repo)
make vault-init  ENV=prod   # prompts for password → configs/prod/.vault_pass (mode 600)
```

**Daily use - declarative client management.**

Define every WireGuard client (phones, laptops) in
`configs/prod/inventory/group_vars/all/main.yml`:

```yaml
wireguard_clients:
  - { name: phone, vpn_ip: 10.10.0.20 }
  - { name: laptop,  vpn_ip: 10.10.0.21, allowed_ips: "0.0.0.0/0" }
```

Run `make provision`. The first stage (`wireguard-keys`) automatically:

1. Generates `privkey`, `pubkey`, `psk` for every new client.
2. Prunes vault entries whose name disappeared from `main.yml`.
3. Re-encrypts `vault.yml` and **auto-commits** the change into the
   `configs/prod/` repo (e.g. `wireguard keys: add phone`).
4. Hands off to the playbook, which renders `[Peer]` sections on the hub
   and writes `build/wireguard/<name>.conf` + `<name>.png` (QR) on your
   controller - ready to scan in the WireGuard mobile app.

**Safety: prune is skipped if `configs/prod/` has uncommitted changes** other
than `vault.yml` itself (catches the "typo in name" scenario where you
are mid-edit). Commit your work and re-run to apply the prune.

**Recovery:** every vault change is committed, so accidentally pruning a
key is recoverable with `git -C configs/prod log -- inventory/group_vars/all/vault.yml`
+ `git -C configs/prod show <sha>:inventory/group_vars/all/vault.yml`.

**Escape hatches** (for debugging - normal use never needs these):

| Command | Purpose |
|---|---|
| `make vault-edit` | Decrypt → `$EDITOR` → re-encrypt |
| `make vault-view` | Read-only peek |
| `make vault-rekey` | Rotate the vault password |

**Test environment.** `make test-env-create` seeds `configs/test/` with a
literal `.vault_pass` containing `test-password`, so `make test-*` exercises
the exact same vault code paths as prod with no manual setup.

## What it does

| Role | Description |
|---|---|
| `service_user` | Creates dedicated `ansible` service account with passwordless sudo and SSH key |
| `base` | Updates apt cache, upgrades packages, installs base packages |
| `admin_user` | Interactive SSH user with configurable shell and packages |
| `admin_dotfiles` | Overlay-syncs `configs/<ENV>/dotfiles/_common/home/` (baseline) and `configs/<ENV>/dotfiles/<hostname>/home/` (per-host override) into the admin user's home directory (manifest-tracked, only manages files explicitly shipped) |
| `ssh_hardening` | Disables root login and password authentication |
| `local_ssh_config` | Generates `~/.ssh/config.d` entries on the control machine |

More roles (Docker, Caddy, WireGuard, borgmatic) are planned.

## Testing

The project includes tooling for local testing with [Incus](https://linuxcontainers.org/incus/) VMs (Linux only).

### One-time Incus setup (Fedora example)

```bash
sudo dnf install -y incus incus-tools
sudo usermod -aG incus-admin $USER
sudo systemctl enable --now incus.socket
sudo incus admin init --minimal
# Log out and back in (or `newgrp incus-admin`) so the group takes effect.
```

If you use `firewalld` (Fedora's default), trust the Incus bridge so VMs get IPv4 via DHCP:

```bash
sudo firewall-cmd --permanent --zone=trusted --add-interface=incusbr0
sudo firewall-cmd --reload
```

For Debian/Ubuntu/Arch hosts, follow [the official Incus install guide](https://linuxcontainers.org/incus/docs/main/installing/).

### Test loop

```bash
make test-env-create    # Launch VMs, install sshd, create initial user
make test-bootstrap     # Bootstrap the ansible service user
make test-provision     # Run full provisioning
make test-env-destroy   # Tear down VMs
```

VM defaults (image, CPU, memory, initial username) live in `.env` - see `.env.example`.

## Further reading

- [Deployment Guide](docs/deployment-guide.md) - multi-site setups, off-site hosts, and VPN connectivity

## License

[Apache 2.0](LICENSE)
