# notifications

Backbone for alert/notification delivery from other roles and from the
user's own scripts. Single supported backend (M3.5): [ntfy](https://ntfy.sh).

## What it does

| Path | Purpose |
|---|---|
| `/usr/local/bin/hsp-notify` | CLI wrapper around `curl` → ntfy |
| `/etc/hsp-notify.env` (0600) | Backend URL + token (rendered from vars) |
| `/etc/systemd/system/hsp-notify-failure@.service` | Template unit called via `OnFailure=` |

The role is **safe to enable unconditionally**. If `notifications_ntfy_url`
is empty, `hsp-notify` becomes a no-op and logs each would-be subject to
the systemd journal under tag `hsp-notify`. Other roles that wire up
`OnFailure=hsp-notify-failure@%n.service` therefore work on hosts that
have not configured a backend yet - failures just don't reach a phone.

## Variables

| Name | Default | Notes |
|---|---|---|
| `notifications_ntfy_url` | `""` | Topic URL, e.g. `https://ntfy.sh/hsp-CHANGEME-CHANGEME`. Empty → inert. |
| `notifications_ntfy_token` | `""` | Bearer token, only for self-hosted ntfy with auth. Pull from vault. |
| `notifications_ntfy_priority_default` | `default` | One of `min`, `low`, `default`, `high`, `urgent`. |

## Using `hsp-notify` from your own scripts

```bash
hsp-notify "Backup finished" "borg create succeeded in 12m43s"
hsp-notify --priority urgent --tags rotating_light \
           "Disk failing: /dev/sdb" \
           "$(smartctl -H /dev/sdb)"
```

The same CLI is used by `scheduled_jobs`, `systemd_units`,
`smart_monitoring`, and the `needrestart` extension of `auto_updates`.

## Privacy considerations

Mobile push uses **Firebase Cloud Messaging (FCM)** on Android (Play Store
build) and **Apple Push Notification service (APNs)** on iOS. Both are
unavoidable: Android and iOS forbid third-party apps from holding
background sockets, so the push payload always traverses Google or Apple
infrastructure to reach your phone.

Implications:

- **Notification body and title are visible** to the operator of your
  ntfy server (Heckel for `ntfy.sh`, you for self-hosted), to FCM/APNs,
  and - for `ntfy.sh` - to its TLS terminator. **Never put secrets,
  passwords, or tokens in `hsp-notify` arguments.** Stick to operational
  metadata: "Disk failing on hsp-app", "sched-backup-borg failed",
  "12 packages need restart".
- **Topic name is the only authentication on `ntfy.sh`.** Anyone who
  knows the URL can read and write. Generate a long random suffix
  (`openssl rand -hex 6`) and keep the URL out of git via vault.
- **Treat the topic as a secret.** If a real topic was ever committed,
  pasted into an issue, or otherwise exposed, rotate it: pick a new
  random topic, update `notifications_ntfy_url`, re-provision, and
  unsubscribe the old topic on every device.
- **Self-hosted iOS push** still goes through `ntfy.sh` as an APNs
  relay (Apple developer cert constraint), but only a "wake up" poke
  is sent through it - the body is fetched directly from your server
  over HTTPS by the iOS app. Configure
  [`upstream-base-url: https://ntfy.sh`](https://docs.ntfy.sh/config/#ios-instant-notifications)
  in your `server.yml` to enable instant iOS delivery.
- **Android F-Droid build** does not use FCM at all: it keeps a
  websocket open to your server for instant delivery (battery cost is
  noticeable but small). Best privacy posture if you self-host.

For homelab-grade alerts (disk health, failed timers, needrestart
output) the public `ntfy.sh` instance is fine - none of that content is
sensitive. Self-host once you find yourself wanting per-user auth, an
audit log, or HA.

## Picking a topic URL

ntfy treats topic names as bearer secrets - anyone who knows the URL can
publish and subscribe. For the public `ntfy.sh` instance, pick a long
random topic name:

```bash
echo "https://ntfy.sh/hsp-$(hostname -s)-$(openssl rand -hex 6)"
```

For a self-hosted instance, deploy the official `binwiederhier/ntfy`
container as a compose stack under `configs/<env>/stacks/` and point
`notifications_ntfy_url` at it (e.g. `https://ntfy.your-domain.tld/alerts`).
Use `notifications_ntfy_token` if you enabled access control.

## Vault example

```yaml
# configs/<env>/inventory/group_vars/all/vault.yml (encrypted)
vault_notifications_ntfy_token: "tk_xxxxxxxxxxxxx"

# configs/<env>/inventory/group_vars/all/main.yml
notifications_ntfy_url: "https://ntfy.your-domain.tld/hsp-alerts"
notifications_ntfy_token: "{{ vault_notifications_ntfy_token }}"
```

## Smoke test

After a successful `make provision`, fire a test notification at every
host in the env:

```bash
make notify-test ENV=prod              # all `servers` group
make notify-test ENV=prod HOST=hsp-app # one host
```

Each host runs `hsp-notify` over SSH; the message lands on your phone if
`notifications_ntfy_url` is configured, or in the journal under tag
`hsp-notify` if you have not pointed the role at a backend yet.
