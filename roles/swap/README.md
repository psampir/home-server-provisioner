# swap

Ensures a host has at least `swap_size` bytes of total active swap.
Disabled by default - opt in per host (or group) by setting
`swap_size`.

## Mental model: top-up to target

`swap_size` is a **declarative target** for total active swap on the
host, not a literal "create me a swapfile of this size" instruction.

On every run the role:

1. Sums all active swap that it does **not** own (Debian installer
   partition, zram, hand-written swapfiles at other paths). Call this
   `external`.
2. Computes `target_file = max(0, swap_size - external)`.
3. If `target_file` is below `swap_min_file_bytes` (default 64 MiB),
   removes the role-managed file entirely - the host already has
   enough swap from elsewhere.
4. Otherwise creates / resizes / activates the role-managed file at
   `swap_file_path` to exactly `target_file` bytes.

This means the operator only ever has to think about *how much swap
this host needs*. The role figures out how much (if any) of that has
to be a managed file.

### Worked examples

| External swap (e.g. installer partition) | `swap_size` | Result                                                  |
|------------------------------------------|-------------|---------------------------------------------------------|
| 0                                        | `""`        | nothing (default; role is a no-op)                      |
| 1 GiB partition                          | `""`        | nothing - the partition is left alone                   |
| 0                                        | `"2G"`      | 2 GiB role-managed file. Total: 2 GiB.                  |
| 1 GiB partition                          | `"2G"`      | 1 GiB role-managed file. Total: **2 GiB.**              |
| 1 GiB partition                          | `"1G"`      | no role file (target satisfied externally). Total: 1 GiB. |
| 2 GiB partition                          | `"1G"`      | no role file. Total: 2 GiB (more than asked).           |
| 1 GiB partition + 512 MiB role file      | `"1G"`      | role file removed. Total: 1 GiB.                        |
| 1 GiB partition + 512 MiB role file      | `"2G"`      | role file resized to 1 GiB. Total: 2 GiB.               |

### Coexistence with installer-provided swap

The role **only ever owns the file at `swap_file_path`** (default
`/swapfile`). It will never `swapoff`, edit, or delete:

* Swap partitions created by the Debian installer (`/dev/sdaN`,
  `/dev/nvme0n1pN`, …).
* `systemd-zram-generator` devices (`/dev/zram0`).
* Swapfiles at any path other than `swap_file_path`.

`/swapfile` is the systemd-recommended location for swapfiles and
does not collide with installer-managed partitions (which live at
block-device paths). If a previous run of the role (or some other
operator) left a file at `/swapfile`, the role will adopt and manage
it. Set `swap_file_path` to a different location if that's not what
you want.

## Why a swap role at all?

Modern small servers often skip swap entirely (zram is enough on a
laptop), but on a self-hosted box it's still useful to have a few
hundred MB to a couple of GB of disk-backed swap so the OOM killer
doesn't blow away long-running services the moment a single container
spikes its allocation.

`base_sysctls.vm.swappiness=10` (set by the `base` role) keeps the
kernel from touching swap unless it really has to.

## Variables

| Variable                | Default                | Notes |
|-------------------------|------------------------|-------|
| `swap_size`             | `""` (disabled)        | Human-readable total target, e.g. `"512M"`, `"1G"`. Empty disables the role and tears down any role-managed file. |
| `swap_file_path`        | `/swapfile`            | Where the role-managed file lives. |
| `swap_fstab_options`    | `sw,nofail`            | `nofail` so a corrupt/missing swapfile never blocks boot. |
| `swap_min_file_bytes`   | `67108864` (64 MiB)    | Below this, the role drops the file instead of creating a tiny one. |

## Caveats

* `fallocate` requires the underlying filesystem to support
  pre-allocated extents. ext4, xfs, btrfs (with `nodatacow` on the
  swap dir) and zfs (recent enough) all do; if you hit
  `fallocate: fallocate failed: Operation not supported`, switch to
  `dd` manually or move `swap_file_path` to a different mountpoint.
* On btrfs, swapfiles must live on a subvolume mounted with
  `nodatacow` and without compression. The role does NOT enforce
  this; pick `swap_file_path` accordingly.
* Resizing reads the current file size from `stat`; if the file is
  sparse (mistakenly created with `dd` + `seek`), the comparison may
  pass even though only a fraction of bytes are allocated. Don't
  hand-craft swapfiles outside the role.
* The role won't shrink an oversized installer swap partition. If
  external swap exceeds `swap_size`, total active swap simply ends
  up larger than the target - the role logs a debug message and
  moves on.


