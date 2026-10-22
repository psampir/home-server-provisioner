# time_sync

Keeps the host clock synchronized with `systemd-timesyncd`.

## What it does

1. Installs `systemd-timesyncd`.
2. Optionally writes `/etc/systemd/timesyncd.conf.d/10-ansible.conf` with
   custom NTP and fallback servers.
3. Unmasks, enables, and starts `systemd-timesyncd`.

## Variables

| Variable | Default | Description |
|---|---|---|
| `time_sync_ntp_servers` | `[]` | NTP servers for the `NTP=` line |
| `time_sync_fallback_ntp_servers` | `[]` | Servers for the `FallbackNTP=` line |

With both lists empty the role keeps the distribution defaults and does not
create the drop-in.

## Notes

- The role uses `systemd-timesyncd`, not chrony or ntpd. Do not enable a
  second time daemon on the same host.
- A host behind a restrictive firewall needs UDP 123 outbound to its NTP
  servers.
- `timedatectl` shows synchronization state and the current servers. Use it
  to verify the role after provisioning.
- Custom servers are written to a drop-in, so package updates do not
  overwrite them.
