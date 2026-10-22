# local_ssh_config

Generates SSH client configuration on the controller so `ssh <hostname>`
works for every managed server without editing `~/.ssh/config` by hand.

## What it does

1. Creates `~/.ssh/config.d` with mode `0700`.
2. Renders `~/.ssh/config.d/home-server-provisioner-<env>` with one `Host`
   block per host in the `servers` group.
3. Ensures `~/.ssh/config` exists and starts with `Include config.d/*`.

Each block contains `HostName` (the inventory `ansible_host`), `User` (the
inventory `admin_user_name`), and `IdentityFile`.

## Variables

| Variable | Default | Description |
|---|---|---|
| `local_ssh_config_dir` | `~/.ssh/config.d` | Directory for generated files |
| `local_ssh_config_env_name` | `HSP_ENV` or `default` | Environment suffix in the filename |
| `local_ssh_config_file` | `config.d/home-server-provisioner-<env>` | Generated file |
| `local_ssh_config_host_prefix` | empty | Prefix added to every `Host` alias |
| `local_ssh_config_private_key` | `ANSIBLE_PRIVATE_KEY_FILE` or `~/.ssh/id_ed25519` | Key used by the entries |

## Notes

- The role targets `localhost` in `site.yml` and runs with
  `become: false`. It writes only under the invoking user's home directory.
- Only `groups['servers']` is covered. External WireGuard clients are not
  managed hosts and do not get an entry.
- The generated file uses `ansible_host` directly. It does not add a
  `ProxyJump` entry. Hosts behind NAT are expected to be reachable through
  the WireGuard tunnel, so the VPN address in `ansible_host` is enough.
- Run `make ssh-config ENV=<env>` to regenerate the file without a full
  provision.
- The `Include config.d/*` line is added once. Existing content in
  `~/.ssh/config` is left in place.
