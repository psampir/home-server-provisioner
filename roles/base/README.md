# base

Baseline system configuration: apt cache and upgrade, base packages, the
grub-pc pre-seed for unattended upgrades, and the kernel sysctls applied by
`base_sysctl_apply`.

## Resolver preflight

`base` runs before `dns_client` in `site.yml`, and every apt task needs DNS.
A fresh Debian 13 host using `ifupdown` + `dhcpcd` can boot with an empty
`/etc/resolv.conf` (no `nameserver` line), which makes the first
`apt-get update` fail before `dns_client` ever gets a chance to write the
real configuration.

The role therefore:

1. Adds `nohook resolv.conf` to `/etc/dhcpcd.conf` when that file exists, so
   dhcpcd does not overwrite the file on the next lease renewal. The line is
   inserted before the first `interface`, `ssid` or `profile` block (global
   scope) and is idempotent.
2. Checks `/etc/resolv.conf` for a `nameserver` line.
3. Appends `nameserver {{ base_resolv_fallback_nameserver }}` (default
   `1.1.1.1`) only when no nameserver is present, leaving any existing
   `search` or `options` lines alone. A working resolver, including the
   systemd-resolved stub, is left untouched.

`dns_client` later replaces the placeholder with the hub resolver, so this
is a bootstrap safety net rather than a permanent DNS configuration. Set
`base_resolv_fallback_nameserver` to an internal resolver if the host cannot
reach the public internet directly.

## Variables

| Variable | Default | Description |
|---|---|---|
| `base_packages` | `[curl]` | Packages installed after the upgrade |
| `base_grub_install_device` | `""` | GRUB device for the grub-pc pre-seed; empty auto-detects |
| `base_sysctls` | see `defaults/main.yml` | Dict rendered to `/etc/sysctl.d/99-hsp.conf` |
| `base_resolv_fallback_nameserver` | `1.1.1.1` | Resolver written only when `/etc/resolv.conf` has none |
