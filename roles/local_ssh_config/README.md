# local_ssh_config

Generates SSH client configuration on the controller so `ssh <hostname>`
works for every managed server without editing `~/.ssh/config` by hand.

## What it does

1. Creates `~/.ssh/config.d` with mode `0700`.
2. Renders `~/.ssh/config.d/home-server-provisioner-<env>` with one
   `Host` block per host in the `servers` group.
3. Ensures `~/.ssh/config` exists and starts with `Include config.d/*`.

For application and backup hosts (the default `wireguard_role: peer`),
the role writes two aliases:

```text
Host <name>          HostName <vpn_ip>     # works anywhere over WireGuard
Host <name>-lan      HostName <lan_ip>     # direct LAN, fastest at home
```

The hub is identified by `wireguard_role: hub`, the same marker the
`wireguard` role uses. Its main alias always points at `ansible_host`,
because its `vpn_ip` only exists inside the tunnel. The role does not
depend on a `vpn_server` group name.

Hosts without `vpn_ip` get a single alias pointing at `ansible_host`. If
`lan_ip` is missing, the `<name>-lan` alias falls back to `ansible_host`
and is omitted when it would duplicate the main address.

## Inventory fields

| Field | Purpose |
|---|---|
| `vpn_ip` | WireGuard address, primary alias for peers |
| `lan_ip` | LAN address used by `<host>-lan` |
| `wireguard_role` | `hub` for the single hub, `peer` or unset for the rest |
| `ansible_host` | address Ansible uses; for the hub, its public address |
| `admin_user_name` | SSH `User` for every generated block |

The private inventory can make `ansible_host` follow an environment
switch, for example `HSP_REMOTE=1` for VPN and the default for LAN. The
generated SSH aliases are independent of that switch and always provide
both paths.

## Variables

| Variable | Default | Description |
|---|---|---|
| `local_ssh_config_dir` | `~/.ssh/config.d` | Directory for generated files |
| `local_ssh_config_env_name` | `HSP_ENV` or `default` | Environment suffix in the filename |
| `local_ssh_config_file` | `config.d/home-server-provisioner-<env>` | Generated file |
| `local_ssh_config_host_prefix` | empty | Prefix added to every alias, including `-lan` |
| `local_ssh_config_private_key` | `ANSIBLE_PRIVATE_KEY_FILE` or `~/.ssh/id_ed25519` | Key used by the entries |

## Notes

- The role targets `localhost` in `site.yml` and runs with
  `become: false`. It writes only under the invoking user's home directory.
- Only `groups['servers']` is covered. External WireGuard clients are not
  managed hosts and do not get an entry.
- The generated file does not add a `ProxyJump`. Hosts behind NAT are
  reached through the WireGuard tunnel on their `vpn_ip`; the `-lan`
  alias is for direct access at home.
- On first contact with a VPN address, verify the host key fingerprint
  against the LAN entry before accepting it. A changed key means the host
  was reinstalled or the tunnel is being intercepted.
- Run `make ssh-config ENV=<env>` to regenerate the file without a full
  provision. Regenerate after upgrading to a release that adds the
  `-lan` aliases.
