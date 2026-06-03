# custom_scripts

Ship arbitrary user-supplied scripts to every managed host's
`/usr/local/bin/`. Scripts live in your env's `configs/<env>/scripts/`
tree on the controller; the role copies them verbatim and forces
mode `0755`.

## Layout (controller side)

```
configs/<env>/scripts/
├── _common/                  # shipped to every host
│   ├── hsp-rotate-old-stuff
│   └── nightly-summary.sh
├── hsp-app/                  # only to host hsp-app
│   └── app-specific-tool.py
└── hsp-vpn/                  # only to host hsp-vpn
    └── vpn-housekeeping
```

Files at the top of `_common/` go to **every** host. A file in
`<inventory_hostname>/` with the same name overrides the `_common/` one
(full file replace, no merging). README.md / .gitkeep / .gitignore are
ignored by the discovery walker.

## Layout (target side)

Every script lands in `/usr/local/bin/`, mode `0755`, owned by `root:root`.

The original file suffix is **kept** - `nightly-summary.sh` becomes
`/usr/local/bin/nightly-summary.sh`. The suffix is part of the
user-facing command name (you call it as `nightly-summary.sh`).
This is intentional: it makes the language obvious from the command
line and keeps the shebang authoritative.

If you set `custom_scripts_prefix: "hsp-"`, every installed script is
renamed `<prefix><original-name>`, e.g. `nightly-summary.sh` →
`/usr/local/bin/hsp-nightly-summary.sh`. Default prefix is empty.

## Manifest-based cleanup

The role tracks managed destination paths in
`/var/lib/home-server-provisioner/custom_scripts.manifest`. Files
listed in the previous manifest but missing from the current merged
overlay are removed on the next run. Other contents of `/usr/local/bin/`
are never touched.

## Variables

| Name | Default | Notes |
|---|---|---|
| `custom_scripts_src_root` | `{{ inventory_dir }}/../scripts` | Set to `""` to disable + cleanup |
| `custom_scripts_common_subdir` | `_common` | Baseline subtree |
| `custom_scripts_host_subdir` | `{{ inventory_hostname }}` | Host overlay subtree |
| `custom_scripts_install_dir` | `/usr/local/bin` | Where files land |
| `custom_scripts_prefix` | `""` | Optional filename prefix |
| `custom_scripts_manifest_path` | `/var/lib/home-server-provisioner/custom_scripts.manifest` | Manifest location |

## Composing with `scheduled_jobs`

`scheduled_jobs` references scripts by absolute path in `command:`.
Drop a script under `configs/<env>/scripts/_common/backup-borg.sh`,
let `custom_scripts` install it as `/usr/local/bin/backup-borg.sh`,
and reference that path from a `scheduled_jobs_host` entry. There is
no implicit linkage - the two roles compose explicitly via the
filesystem.

## Notes

- **No shebang validation.** The role does not inspect file content;
  it just copies and chmods. Bring your own shebang and tooling.
- **No language tooling installation.** If your script needs `python3`,
  `jq`, `curl`, etc., install them via your usual mechanism (e.g. a
  `base_packages_extra` list, or a small wrapper role you write
  yourself).
- **You can also use this role to ship `hsp-notify` callers.** The
  `notifications` role's `hsp-notify` is unconditionally available on
  every host once that role runs, so any custom script can call it
  without further setup.
