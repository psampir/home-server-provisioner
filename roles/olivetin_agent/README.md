# olivetin_agent

Host-side agent for the OliveTin console. It installs the operation
wrappers and a dedicated `olivetin` SSH user whose sudo rights are limited
to those wrappers. It is disabled by default and never grants a general
shell, unrestricted `apt-get`, Docker access or a password login.

## What it installs

| Wrapper | Allowed arguments | Purpose |
|---|---|---|
| `/usr/local/sbin/hsp-apt` | `check`, `upgrade` | Refresh package lists, simulate or run a safe upgrade |
| `/usr/local/sbin/hsp-needrestart` | none | Show services and kernels that need a restart |
| `/usr/local/sbin/hsp-reboot` | `schedule`, `cancel` | Schedule `shutdown -r +5` or cancel it |
| `/usr/local/sbin/hsp-backup-check` | none | `borgmatic check` or the local restic check |
| `/usr/local/sbin/hsp-journal-vacuum` | none | `journalctl --vacuum-time=30d` |
| `/usr/local/sbin/hsp-smart` | `short`, `status` | Start or read a short SMART test |

`hsp-apt upgrade` uses `apt-get upgrade --with-new-pkgs`, not
`full-upgrade`, and never runs `autoremove`. It is non-interactive and pins
`needrestart` to list-only.

## Variables

| Variable | Default | Description |
|---|---|---|
| `olivetin_agent_enabled` | `false` | Install the user, key and wrappers |
| `olivetin_agent_user` | `olivetin` | Dedicated agent user |
| `olivetin_agent_ssh_public_keys` | `[]` | Keys allowed to log in as the agent |
| `olivetin_agent_client_key_path` | `""` | Optional client key path on the OliveTin host |
| `olivetin_agent_client_private_key` | `""` | Optional client key material (no_log) |
| `olivetin_agent_client_key_owner` | `1000` | Owner of the client key |
| `olivetin_agent_client_key_group` | `1000` | Group of the client key |

The `authorized_keys` entries use `restrict`, so the key cannot forward
ports, agents or X11. Sudo is limited to the exact wrapper commands in
`/etc/sudoers.d/90-olivetin`.

## Example

```yaml
olivetin_agent_enabled: true
olivetin_agent_ssh_public_keys:
  - "{{ vault_olivetin_ssh_public_key }}"
```

On the host that runs the OliveTin container, also set
`olivetin_agent_client_key_path` and `olivetin_agent_client_private_key`.
The stack mounts that file read-only at `/config/ssh/id_ed25519`; the key
must be `0600` for OpenSSH.
