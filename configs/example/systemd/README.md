# systemd unit drop-in

Files placed here are copied verbatim to `/etc/systemd/system/` on
managed hosts by the `systemd_units` role. Use this for arbitrary
systemd units that don't fit the simpler `scheduled_jobs` model
(long-running daemons, socket activation, template units, etc.).

Layout:

```
systemd/
├── _common/<unit>.{service,timer,...}   # applied to every host
└── <inventory_hostname>/<unit>          # host-specific overlay
                                         # (wins on basename collision)
```

Supported suffixes: `.service`, `.timer`, `.socket`, `.target`,
`.mount`, `.path`, `.slice`.

For automatic failure notifications, add this to your unit's
`[Unit]` section:

    OnFailure=hsp-notify-failure@%n.service

See `roles/systemd_units/README.md` for the full reference.
