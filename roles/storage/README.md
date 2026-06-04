# storage

Format-on-empty + mount role for block devices on a Debian 13 host.
Disabled by default (`storage_volumes: []`). Populate `storage_volumes`
in `host_vars/<hostname>.yml` to manage one or more disks.

## What it does

For each entry in `storage_volumes`:

1. Verifies the device path exists.
2. Probes the existing filesystem with `blkid`.
3. **If empty** → creates the requested filesystem (`mkfs.<fstype>`).
4. **If filesystem matches** → no-op, reuses the existing UUID.
5. **If filesystem differs** → **fails by design**, unless
   `force_format: true` is set on that volume (then `wipefs -a` +
   `mkfs.<fstype>`).
6. Creates the mountpoint directory with `owner`/`group`/`mode`.
7. Adds an fstab entry by **UUID** with `mount_opts` and mounts.

A per-host manifest at `/var/lib/home-server-provisioner/storage.manifest`
tracks managed mountpoints. Removing a volume from `storage_volumes`
between runs triggers symmetric cleanup: `umount` → fstab entry removed
→ mountpoint `rmdir`d (**fail-safe**: non-empty dirs are left alone, so
a failed `umount` cannot result in `rm -rf` on a still-mounted
filesystem).

## What it does NOT do

- **Never overwrites an existing filesystem** without explicit per-volume
  `force_format: true`.
- **Never partitions** - operate on a partition or a whole disk that you
  intend to use as a single filesystem.
- **No resize** - to enlarge a volume, do it manually with the
  appropriate fs-specific tool (e.g. `resize2fs`).
- **No backup** - there is none. `force_format` will destroy data.

## Variables

```yaml
storage_volumes: []
storage_manifest_path: /var/lib/home-server-provisioner/storage.manifest
```

### Per-volume schema

| key            | required | default            | notes                                                |
|----------------|----------|--------------------|------------------------------------------------------|
| `device`       | yes      | -                  | Use `/dev/disk/by-id/...` for stable identification. |
| `mount`        | yes      | -                  | Absolute path.                                       |
| `fstype`       | yes      | -                  | `ext4` \| `xfs` \| `btrfs`.                          |
| `mkfs_opts`    | no       | `[]`               | Extra args to `mkfs.<fstype>`.                       |
| `mount_opts`   | no       | `defaults,nofail`  | `nofail` keeps boot working with a missing disk.     |
| `owner`        | no       | `root`             | Mountpoint dir owner.                                |
| `group`        | no       | `root`             | Mountpoint dir group.                                |
| `mode`         | no       | `"0755"`           | Mountpoint dir mode.                                 |
| `force_format` | no       | `false`            | **Destructive**; allow re-format on fstype mismatch. |

## Example

```yaml
storage_volumes:
  - device: /dev/disk/by-id/ata-WDC_WD40EFRX-68N32N0_WD-WCC7K0XYZ
    mount: /srv/data
    fstype: ext4
    mount_opts: "defaults,nofail,noatime"
    owner: root
    group: root
    mode: "0755"
```

## Tips

- Always look up the `/dev/disk/by-id/` path on the host once
  (`ls -l /dev/disk/by-id/`) and put that into your inventory. Kernel
  device names (`/dev/sda`) are not stable across reboots if you add or
  rearrange disks.
- Cleanup is conservative on purpose: the role will *not* delete a
  mountpoint directory that still has files in it. If you really want
  the directory gone, `rmdir` it yourself after confirming the volume
  is gone.
