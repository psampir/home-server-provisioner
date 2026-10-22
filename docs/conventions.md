# Conventions

Short, factual rules this repository follows. They are why `ansible-lint`
(profile `production`) passes with only two documented `args[module]`
exceptions for `community.general.ufw`, and why a role's interface is
readable from its directory alone.

## Role names

`snake_case`. **Plural** when the role manages a collection of things -
`systemd_units`, `scheduled_jobs`, `custom_scripts`, `network_mounts`.
**Singular** for a single concern - `firewall`, `swap`, `wireguard`,
`borgmatic`.

## Variables

Every variable a role introduces is prefixed with the role name (`<role>_`)
and declared in that role's `defaults/main.yml` (or `vars/` when the author
must control it). Tasks that only *use* a name are not enough: `ansible-lint`
lints declared names, and an undeclared variable is invisible in the role's
public interface.

### Deliberate exceptions: inventory contracts

A handful of names are per-host data consumed by several roles rather than
input to one role. They are intentionally **not** prefixed:

| Name | Consumers | Why it stays unprefixed |
|---|---|---|
| `vpn_ip` | `wireguard`, `dnsmasq`, `borgmatic`, stacks | One address per host, read by many roles and written by every inventory. |
| `bootstrap_user` | `bootstrap.yml`, `base`, `admin_user` | The only account that exists before `admin_user` is created. |
| `ansible_*` | Ansible itself | Connection variables owned by the inventory/Ansible, not by a role. |

Renaming these would break every existing inventory and gain nothing, so they
are documented exceptions instead.

## No legacy aliases

This project is pre-release, so every role, variable, and make target has
exactly one name. A rename is a plain rename: no compatibility shim, no
`default(old_name)` indirection, no deprecated spelling kept around. The old
name stops working in the same commit that introduces the new one, and every
reference in docs, inventory examples, and scripts is updated with it.

## Templates and files

Prefer `<role>.<purpose>.<ext>.j2` for new templates, for example
`scheduled_jobs.service.j2`, `borgmatic.timer-dropin.conf.j2`, and
`base/templates/99-hsp.conf.j2`. Some templates mirror an upstream package
path instead, such as `ups.conf.j2` or `resolv.conf.j2`; the destination
documented in the task and role README is the source of truth, not the
filename convention.

## Role pairing

`borgmatic` (backup **source**) and `borg_repo` (backup **target**) are two
different tools in one pipeline, not a naming inconsistency. They are paired,
not merged, and each README states which side it is.

## Makefile targets

`<domain>-<action>`: `wireguard-keys`, `wireguard-render`, `vault-init`,
`vault-edit`, `test-env-create`, `test-smoke`. There are no short aliases - the
canonical `<domain>-<action>` name is the only name, and every target carries a
`##` help comment so `make help` lists it.
