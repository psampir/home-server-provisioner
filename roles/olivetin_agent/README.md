# olivetin_agent

Host-side agent for the OliveTin console. It creates a dedicated `olivetin`
SSH user and renders an exact sudo allowlist. The operation scripts
themselves belong to the environment and are installed with `custom_scripts`;
this role does not ship or install any of them. It is disabled by default and
never grants a general shell, unrestricted `apt-get`, Docker access or a
password login.

## Reference operation scripts

The public reference implementations live in
`configs/example/scripts/_common/`. They are examples, not installed by this
role: copy them into your environment's `scripts/_common/` (or write your
own) and let `custom_scripts` install them to `/usr/local/bin`.

| Script | Allowed arguments | Purpose |
|---|---|---|
| `/usr/local/bin/hsp-apt` | `check`, `upgrade`, `autoremove-check`, `autoremove` | Refresh package lists, simulate or run a safe upgrade, preview or remove unused packages |
| `/usr/local/bin/hsp-needrestart` | none | Show services and kernels that need a restart |
| `/usr/local/bin/hsp-reboot` | `schedule`, `cancel` | Schedule a reboot in 5 minutes with a transient systemd timer, or cancel it |
| `/usr/local/bin/hsp-backup-check` | none | `borgmatic check` or the local restic check |
| `/usr/local/bin/hsp-journal-vacuum` | none | `journalctl --vacuum-time=30d` |
| `/usr/local/bin/hsp-etckeeper` | none | Show the last `/etc` changes tracked by etckeeper |

`hsp-apt upgrade` uses `apt-get upgrade --with-new-pkgs`, not
`full-upgrade`, and never runs `autoremove`, so an upgrade cannot remove a
package. Unused packages are handled by the separate
`hsp-apt autoremove-check` and `hsp-apt autoremove` actions:
`autoremove-check` only prints the simulated `apt-get autoremove`, and
`autoremove` runs it after showing the same simulation. Neither refreshes the
package lists. It is non-interactive and pins `needrestart` to list-only.

`hsp-reboot schedule` creates a transient `hsp-reboot.timer` with
`systemd-run --on-active=5min`, and `cancel` stops that timer. It does not
use `shutdown -r +5`: shutdown writes `/run/nologin` as soon as it is
scheduled, and `pam_nologin` then refuses the SSH login of the unprivileged
`olivetin` user, so the cancel action could never reach the host. The timer
leaves logins open until the reboot actually starts.

## Variables

| Variable | Default | Description |
|---|---|---|
| `olivetin_agent_enabled` | `false` | Create the user, key and sudo policy |
| `olivetin_agent_user` | `olivetin` | Dedicated agent user |
| `olivetin_agent_ssh_public_keys` | `[]` | Keys allowed to log in as the agent |
| `olivetin_agent_allowed_commands` | `[]` | Exact absolute-path commands allowed through sudo |
| `olivetin_agent_client_key_path` | `""` | Optional client key path on the OliveTin host |
| `olivetin_agent_client_private_key` | `""` | Optional client key material (no_log) |
| `olivetin_agent_client_key_owner` | `1000` | Owner of the client key |
| `olivetin_agent_client_key_group` | `1000` | Group of the client key |

The `authorized_keys` entries use `restrict`, so the key cannot forward
ports, agents or X11. `/etc/sudoers.d/90-olivetin` is rendered verbatim from
`olivetin_agent_allowed_commands`; the role validates absolute paths and
rejects `*`, `?` and newlines, and `visudo` validates the result.

## Adding a privileged action

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
   olivetin_agent_allowed_commands:
     - /usr/local/bin/moj-skrypt restart
   ```

Passing different arguments than the listed ones is denied by sudo, so add
a separate entry for each permitted argument set.

## Example

```yaml
olivetin_agent_enabled: true
olivetin_agent_ssh_public_keys:
  - "{{ vault_olivetin_ssh_public_key }}"
olivetin_agent_allowed_commands:
  - /usr/local/bin/hsp-apt check
  - /usr/local/bin/hsp-apt upgrade
  - /usr/local/bin/hsp-apt autoremove-check
  - /usr/local/bin/hsp-apt autoremove
  - /usr/local/bin/hsp-needrestart
  - /usr/local/bin/hsp-reboot schedule
  - /usr/local/bin/hsp-reboot cancel
  - /usr/local/bin/hsp-backup-check
  - /usr/local/bin/hsp-journal-vacuum
  - /usr/local/bin/hsp-etckeeper
```

On the host that runs the OliveTin container, also set
`olivetin_agent_client_key_path` and `olivetin_agent_client_private_key`.
The stack mounts that file read-only at `/config/ssh/id_ed25519`; the key
must be `0600` for OpenSSH.
