# admin_user

Creates the **interactive** human account on every server - the login used
for SSH, with passwordless `sudo`. This is separate from the `service_user`
account Ansible itself connects as.

## What it does

1. Validates that `admin_user_name` is set.
2. Installs `sudo`, the configured shell (unless it is `bash`/`sh`) and any
   `admin_user_extra_packages`.
3. Creates the user with a home directory and membership in `sudo`
   (`append: true`, so any group memberships the account already has are
   preserved).
4. Grants passwordless sudo through `/etc/sudoers.d/<user>` (validated with
   `visudo`).
5. Authorizes `admin_user_ssh_pubkey` for the account.

## Key variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `admin_user_name` | `""` | **Required.** Login name, e.g. `jan`. |
| `admin_user_uid` | `""` | Optional numeric UID; empty lets the system choose. |
| `admin_user_shell` | `bash` | Shell package/name; resolved to an absolute path. |
| `admin_user_extra_packages` | `[]` | Extra packages installed with the role. |
| `admin_user_ssh_pubkey` | `"{{ service_user_ssh_pubkey }}"` | Key authorized for the account. |

## Pinning the UID

`admin_user_uid` is empty by default, which preserves the previous
behaviour: the system picks the next free UID. Set it when something else
depends on a fixed number - typically containerised apps running with
`PUID=1000` that own their data on the external disks:

```yaml
# group_vars/all/main.yml
admin_user_uid: 1000
```

A fresh install often lands on 1000 by luck, but only an explicit value
guarantees the human user can read and own that data after every rebuild.

**Caveat:** the UID is only applied when the account is created. Changing
`admin_user_uid` for an existing user makes Ansible update the account
(`usermod -u`), but it does **not** migrate ownership of files already on
disk - those keep the old numeric UID and the user may lose access. Set the
UID before the first provision where possible; if you change it later,
`chown -R` the affected paths on the data disks yourself.
