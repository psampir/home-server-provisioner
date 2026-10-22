# hostname

Sets the system hostname from the inventory name and keeps the local
`/etc/hosts` entry in sync.

## What it does

1. Sets the hostname to `inventory_hostname` through systemd.
2. Optionally updates the `127.0.1.1` line in `/etc/hosts` so local
   resolution uses the same name.

## Variables

| Variable | Default | Description |
|---|---|---|
| `hostname_manage_etc_hosts` | `true` | Update the `127.0.1.1` entry in `/etc/hosts` |

## Notes

- The role uses `inventory_hostname`, not `ansible_host`. Rename a host in
  the inventory and re-provision to change the hostname.
- The `127.0.1.1` entry is preferred over changing `127.0.0.1`, which Debian
  expects to remain `localhost`.
- The role does not reboot. Some services pick up the new hostname only
  after a restart; a fresh provision happens before those services start.
