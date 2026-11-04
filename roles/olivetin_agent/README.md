# olivetin_agent

Host-side agent for the OliveTin console. It installs the operation
wrappers and a dedicated `olivetin` SSH user whose sudo rights are limited
to those wrappers. It is disabled by default and never grants a general
shell, unrestricted `apt-get`, Docker access or a password login.

## What it installs

| Wrapper | Allowed arguments | Purpose |
|---|---|---|
| `/usr/local/sbin/hsp-apt` | `check`, `upgrade`, `autoremove-check`, `autoremove` | Refresh package lists, simulate or run a safe upgrade, preview or remove unused packages |
| `/usr/local/sbin/hsp-needrestart` | none | Show services and kernels that need a restart |
| `/usr/local/sbin/hsp-reboot` | `schedule`, `cancel` | Schedule `shutdown -r +5` or cancel it |
| `/usr/local/sbin/hsp-backup-check` | none | `borgmatic check` or the local restic check |
| `/usr/local/sbin/hsp-journal-vacuum` | none | `journalctl --vacuum-time=30d` |
| `/usr/local/sbin/hsp-etckeeper` | none | Show the last `/etc` changes tracked by etckeeper |
| `/usr/local/sbin/hsp-smart` | `short`, `status summary`, `status full` | Start a short SMART test or print a compact/short or full health view |

`hsp-apt upgrade` uses `apt-get upgrade --with-new-pkgs`, not
`full-upgrade`, and never runs `autoremove`, so an upgrade cannot remove a
package. Unused packages are handled by the separate
`hsp-apt autoremove-check` and `hsp-apt autoremove` actions:
`autoremove-check` only prints the simulated `apt-get autoremove`, and
`autoremove` runs it after showing the same simulation. Neither refreshes the
package lists. It is non-interactive and pins `needrestart` to list-only.

## Variables

| Variable | Default | Description |
|---|---|---|
| `olivetin_agent_enabled` | `false` | Install the user, key and wrappers |
| `olivetin_agent_user` | `olivetin` | Dedicated agent user |
| `olivetin_agent_ssh_public_keys` | `[]` | Keys allowed to log in as the agent |
| `olivetin_agent_wrappers` | all wrappers | Wrappers installed and allowed; other known wrappers are removed |
| `olivetin_agent_wrapper_commands` | map | Allowed arguments per wrapper; the sudoers file is generated from it |
| `olivetin_agent_extra_sudo_commands` | `[]` | Extra absolute-path commands allowed through sudo |
| `olivetin_agent_client_key_path` | `""` | Optional client key path on the OliveTin host |
| `olivetin_agent_client_private_key` | `""` | Optional client key material (no_log) |
| `olivetin_agent_client_key_owner` | `1000` | Owner of the client key |
| `olivetin_agent_client_key_group` | `1000` | Group of the client key |

The `authorized_keys` entries use `restrict`, so the key cannot forward
ports, agents or X11. `/etc/sudoers.d/90-olivetin` is rendered from
`olivetin_agent_wrappers` (with its entries in
`olivetin_agent_wrapper_commands`) plus
`olivetin_agent_extra_sudo_commands`. Wrappers not listed in
`olivetin_agent_wrappers` are removed from `/usr/local/sbin` on the next run.

## Custom privileged actions

Sudo remains exact-match: an OliveTin action may only run a command string
that is listed verbatim in the sudoers file. It is **not** generated from
the OliveTin `config.yaml`, so a new action also needs an inventory entry.

1. Put the script in `configs/<env>/scripts/<host>/` (or `_common/` for every
   host) and let `custom_scripts` install it, so it lands in
   `/usr/local/bin/moj-skrypt` owned by root, mode `0755`:

   ```
   configs/<env>/scripts/_common/moj-skrypt
   ```

2. Use it in the OliveTin action with `sudo -n`:

   ```
   ssh ... sudo -n /usr/local/bin/moj-skrypt restart
   ```

3. Allow exactly that command string:

   ```yaml
   olivetin_agent_extra_sudo_commands:
     - /usr/local/bin/moj-skrypt restart
   ```

Passing different arguments than the listed ones is denied by sudo, so add
a separate entry for each permitted argument set. Wildcards are rejected by
the role's assertions.

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
