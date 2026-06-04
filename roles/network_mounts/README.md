# network_mounts_shares

Client-side NFS and CIFS/SMB mount management for a Debian 13 host.
Disabled by default (`network_mounts_shares: []`). Populate `network_mounts_shares`
in `host_vars/<hostname>.yml` or `group_vars/` to mount one or more
remote shares.

This role is a **client only**. It does not run an NFS server or a Samba
server - those are out of scope.

## What it does

For each entry in `network_mounts_shares`:

1. Validates the entry (type, source, mount; CIFS also needs credentials).
2. Installs the matching client package on demand: `nfs-common` for NFS,
   `cifs-utils` for CIFS. Nothing is installed for types you don't use.
3. For CIFS: writes a credentials file under
   `/etc/credentials/<sanitized-mount>` (mode `0600`) from the
   vault-supplied `credentials_username`/`credentials_password` (and
   optional `credentials_domain`), and injects `credentials=<file>`
   into the mount options.
4. Always appends `_netdev` and `nofail` to the mount options, so a
   missing or unreachable share **never blocks boot**.
5. Creates the mountpoint directory with `owner`/`group`/`mode`.
6. Adds an fstab entry and mounts the share (`state: mounted`).

A per-host manifest at
`/var/lib/home-server-provisioner/network_mounts_shares.manifest` tracks managed
mountpoints. Removing an entry between runs triggers symmetric cleanup:
`umount` → fstab entry removed → generated credentials file deleted →
mountpoint `rmdir`d (**fail-safe**: non-empty dirs are left alone).

## What it does NOT do

- **No server side** - no NFS exports, no Samba shares.
- **No autofs / on-demand mounting** - shares are mounted at provision
  time and at boot via fstab.
- **No secret generation** - CIFS credentials come from you (vault).

## Variables

```yaml
network_mounts_shares: []
network_mounts_credentials_dir: /etc/credentials
network_mounts_manifest_path: /var/lib/home-server-provisioner/network_mounts_shares.manifest
```

### Per-mount schema

| key                    | required        | default       | notes                                                       |
|------------------------|-----------------|---------------|-------------------------------------------------------------|
| `type`                 | yes             | -             | `nfs` or `cifs`.                                            |
| `source`               | yes             | -             | NFS: `host:/export`. CIFS: `//host/share`.                  |
| `mount`                | yes             | -             | Absolute local mountpoint.                                  |
| `fstype`               | no              | `type`        | Override the mount(8) fstype, e.g. `nfs4`.                  |
| `mount_opts`           | no              | `""`          | Extra opts; `_netdev,nofail` always appended.              |
| `owner` / `group`      | no              | `root`        | Mountpoint directory ownership.                            |
| `mode`                 | no              | `0755`        | Mountpoint directory mode.                                 |
| `credentials_username` | cifs only       | -             | From vault.                                                |
| `credentials_password` | cifs only       | -             | From vault.                                                |
| `credentials_domain`   | no (cifs)       | -             | Optional workgroup / AD domain.                            |

## Examples

```yaml
network_mounts_shares:
  - type: nfs
    source: "10.10.0.1:/srv/media"
    mount: /mnt/media
    mount_opts: "ro,vers=4.2"

  - type: cifs
    source: "//nas.home/backups"
    mount: /mnt/backups
    owner: borg
    group: borg
    mount_opts: "uid=borg,gid=borg,file_mode=0640,dir_mode=0750"
    credentials_username: "{{ vault_nas_backup_user }}"
    credentials_password: "{{ vault_nas_backup_pass }}"
```

## Notes

- File ownership *inside* a CIFS share is controlled by `uid=`/`gid=`/
  `file_mode=`/`dir_mode=` mount options, not by the mountpoint directory
  perms (which the server masks once mounted). NFS honours server-side
  ownership.
- Because `nofail` is always present, a provisioning run will not fail if
  a share is temporarily unreachable - but the mount task itself will
  still error if the share is reachable yet rejects the mount (bad
  credentials, no export permission, etc.).
