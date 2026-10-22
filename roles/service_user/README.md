# service_user

Creates the non-interactive automation account used by Ansible after the
first bootstrap. It has passwordless sudo and an authorized SSH key, but no
password and no interactive shell by default.

## What it does

1. Installs `sudo`.
2. Creates `service_user_name` as a system user. A system UID keeps UID 1000
   free for the interactive admin user on a fresh host.
3. Writes `/etc/sudoers.d/<name>` with `NOPASSWD:ALL` and validates it with
   `visudo -cf` before installing it.
4. Authorizes `service_user_ssh_pubkey` for the account.

The account is created before `admin_user` so the rest of the first play can
connect with it. The bootstrap playbook uses `bootstrap_user`; the service
account takes over from `base` onwards.

## Variables

| Variable | Default | Description |
|---|---|---|
| `service_user_name` | `ansible` | Account name |
| `service_user_shell` | `/bin/bash` | Login shell for the account |
| `service_user_ssh_pubkey` | contents of `SSH_PUBKEY_FILE` or `~/.ssh/id_ed25519.pub` | Public key authorized for SSH |

Set `SSH_PUBKEY_FILE` in `.env` to use a key other than the controller's
standard ed25519 key.

## Notes

- Passwordless sudo is intentional: the account exists only for Ansible.
  Protect the private key on the controller.
- The role does not disable password login for this account. That is handled
  by `ssh_hardening`, which runs after `admin_user` and `service_user`.
- If the public key file cannot be read on the controller, the role fails
  while rendering the variable. Create the key or point `SSH_PUBKEY_FILE` at
  an existing file.
